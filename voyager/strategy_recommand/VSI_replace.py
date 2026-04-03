
from multiprocessing import Pool

from dataclasses import dataclass
from scipy.stats import false_discovery_control

from voyager.strategy_recommand.MarkovGame import MarkovGame
import numpy as np
import itertools
import cvxpy as cp 
from scipy.spatial import ConvexHull


@dataclass
class CompactStrategy:
    pi: None            # Immediate joint action distribution
    w: None             # Onward values
    v_induced: None     # Value induced


@dataclass
class OneStepLog:
    joint_action_recommended: None
    joint_action_played: None
    new_state: None


# Value set iteration
class VSI:

    def __init__(self, game: MarkovGame, gamma=0.9, delta=1e-2, epsilon=1e-2):
        """ Copy data from game """
        self.P = np.asarray(game.P, dtype=float)
        self.R = np.asarray(game.R, dtype=float)

        self.states = game.states
        # self.agents = range(game.num_agents)
        self.actions_per_agent = game.actions_per_agent
        self.joint_actions = game.joint_actions

        """ Create index sets """
        self.states_idx = range(len(game.states))
        self.agents_idx = range(game.num_agents)
        self.joint_actions_idx = range(len(game.joint_actions))
        self.actions_per_agent_idx = [range(len(actions)) for actions in game.actions_per_agent]
        self.joint_action_idx_tuples = list(itertools.product(*self.actions_per_agent_idx))

        """ Other useful parameters """
        self.gamma = gamma
        self.delta = delta
        self.epsilon = epsilon
        self.xi = (1 - gamma) * min(epsilon, delta / 2)
        vmin = np.min(self.R) / (1 - gamma)
        vmax = np.max(self.R) / (1 - gamma)
        xi = self.xi
        self.grid_lb = np.floor(vmin / xi) * xi - xi    # So that grid_lb is multiple of xi while <= vmin - xi
        self.grid_ub = np.ceil(vmax / xi) * xi + xi     # So that grid_ub is multiple of xi while >= vmax + xi

        value_range = np.arange(self.grid_lb, self.grid_ub + self.xi / 2, self.xi)  # + xi/2 to ensure ub included
        self.grid_points = np.array(list(itertools.product(value_range, repeat=len(self.agents_idx))))

        """ Inducible sets and other stuff """
        self.inducible_value_sets = None    # A list of inducible value sets, each for a state
        self.policy = None
        self.current_strategy = None
        self.history = None

        # For debugging only
        self.count_check_inducibility = 0                           ######################

    """
    ----------------------------------
    Polytope contains
    ----------------------------------
    """
    @staticmethod
    def polytope_contains(polytope, point, tol=1e-8):
        """ Check if point is contained in polytope using CVXPY. """
        num_vertices = len(polytope)
        if num_vertices == 0:
            return False

        # 使用CVXPY构建完全等价的可行性问题
        x = cp.Variable(num_vertices)
        
        # 完全等价于原Gurobi约束
        constraints = [
            x >= 0,  # 等价于lb=0
            x <= 1,  # 等价于ub=1
            cp.sum(x) == 1,  # 等价于x.sum() == 1
            x @ polytope == point  # 等价于point == x @ polytope
        ]
        
        # 构建最小化0的可行性问题（完全等价）
        prob = cp.Problem(cp.Minimize(0), constraints)
        
        try:
            #prob.solve(solver=cp.ECOS, verbose=False)
            prob.solve(verbose=False)
            # 完全等价的返回值逻辑
            if prob.status == cp.OPTIMAL:
                return True
            else:
                return False
        except:
            return False


    """
    -----------------------------------------
    Value sets to convex hulls
    -----------------------------------------
    """
    @staticmethod
    def value_sets_to_convex_hulls(VS):
        """ Convert value sets in VS to their convex hulls in vertex representation. """
        if VS is None: return None

        VS_hull = [None] * len(VS)
        for i, vs in enumerate(VS):
            if len(vs) >= 3:  # scipy.spatial.ConvexHull does not take fewer than 3 points
                hull = ConvexHull(vs).vertices
            else:
                hull = range(len(vs))
            VS_hull[i] = np.array([VS[i][j] for j in hull])
        return VS_hull

    """
    -----------------------------------------
    Value sets identical
    -----------------------------------------
    """
    @staticmethod
    def value_sets_identical(VS1, VS2, tol=1e-8):
        """ Check if two value-set functions VS1 and VS2 contain identical value sets. """
        if VS1 is None and VS2 is None: return True
        elif VS1 is None or VS2 is None: return False
        elif len(VS1) != len(VS2): return False

        _VS1 = VSI.value_sets_to_convex_hulls(VS1)
        _VS2 = VSI.value_sets_to_convex_hulls(VS2)

        VS1_in_VS2 = all(VSI.polytope_contains(_VS2[i], p, tol)
                         for i, vs in enumerate(_VS2)
                         for p in _VS1[i])
        VS2_in_VS1 = all(VSI.polytope_contains(_VS1[i], p, tol)
                         for i, vs in enumerate(_VS1)
                         for p in _VS2[i])

        return VS1_in_VS2 and VS2_in_VS1

    """
    ----------------------------------
    Trim distribution
    ----------------------------------
    """
    @staticmethod
    def trim_distribution(p: np.ndarray, tol=1e-8):
        if p.sum() > 1 + tol or p.sum() < 1 - tol:
            raise RuntimeError(f"Probabilities do not sum up to 1 (tol = {tol}).")
        elif np.max(0 - p) > tol:
            raise RuntimeError(f"Probabilities are not non-negative (tol = {tol}).")

        p = np.clip(p, 0, None)
        p = p / p.sum()
        return p

    """
    ----------------------------------
    Joint action after deviation
    ----------------------------------
    """
    def deviate(self, joint_action_idx: int, agent_idx: int, new_action_idx: int):
        """ Returns: joint action resulting from agent deviating to new action. """
        A_vec = self.joint_action_idx_tuples[joint_action_idx]
        A_vec = list(A_vec)   # Convert tuple to list so that it's modifiable
        A_vec[agent_idx] = new_action_idx
        return self.joint_action_idx_tuples.index(tuple(A_vec))

    """
    -------------------
    Check inducibility
    -------------------
    """
    def check_inducibility(self, VS, state, target_values):
        """
        Check if target values are inducible using CVXPY (完全等价替换).
        """
        # 保持完全相同的输入处理逻辑
        if isinstance(target_values[0], np.ndarray):
            single_target_value = False
        else:
            target_values = [target_values]
            single_target_value = True

        s = self.states.index(state)
        P = self.P
        R = self.R
        gamma = self.gamma
        xi = self.xi

        VS = VSI.value_sets_to_convex_hulls(VS)

        num_states = len(self.states_idx)
        num_agents = len(self.agents_idx)
        num_joint_actions = len(self.joint_actions_idx)

        results = [None] * len(target_values)
        
        # 对每个目标值分别求解（保持原逻辑）
        for k, v in enumerate(target_values):
            # 使用CVXPY定义完全等价的变量
            v_induced = cp.Variable(num_agents)
            pi = cp.Variable(num_joint_actions)
            
            # 创建完全等价的z变量结构
            z = {}
            for A, B, ss in itertools.product(self.joint_actions_idx, self.joint_actions_idx, self.states_idx):
                z[A, B, ss] = cp.Variable(len(VS[ss]))
            
            # 构建完全等价的约束
            constraints = []
            
            # 1. 变量边界约束（完全等价）
            constraints.extend([v_induced >= self.grid_lb, v_induced <= self.grid_ub])
            constraints.extend([pi >= 0, pi <= 1])
            
            for A, B, ss in itertools.product(self.joint_actions_idx, self.joint_actions_idx, self.states_idx):
                constraints.append(z[A, B, ss] >= 0)
            
            # 2. 目标约束（完全等价）
            for i in self.agents_idx:
                constraints.append(v_induced[i] >= v[i] - xi)
                constraints.append(v_induced[i] <= v[i] + xi)
            
            # 3. Bellman约束（完全等价）
            for i in self.agents_idx:
                # 构建完全等价的Bellman方程
                bellman_expr = 0
                for A in self.joint_actions_idx:
                    bellman_expr += R[i, s, A] * pi[A]
                    for ss in self.states_idx:
                        # 完全等价于原表达式
                        bellman_expr += gamma * cp.sum(z[A, A, ss] @ VS[ss][:, i]) * P[s, A, ss]
                
                constraints.append(v_induced[i] == bellman_expr)
            
            # 4. IC约束（完全等价）
            for i in self.agents_idx:
                for a in self.actions_per_agent_idx[i]:
                    for b in self.actions_per_agent_idx[i]:
                        if a == b:
                            continue
                        
                        ic_expr = 0
                        for A in self.joint_actions_idx:
                            if self.joint_action_idx_tuples[A][i] == a:
                                # 立即奖励部分（完全等价）
                                ic_expr += pi[A] * (R[i, s, A] - R[i, s, self.deviate(A, i, b)])
                                
                                # 未来价值部分（完全等价）
                                for ss in self.states_idx:
                                    term1 = cp.sum(z[A, A, ss] @ VS[ss][:, i]) * P[s, A, ss]
                                    term2 = cp.sum(z[A, self.deviate(A, i, b), ss] @ VS[ss][:, i]) * P[s, self.deviate(A, i, b), ss]
                                    ic_expr += gamma * (term1 - term2)
                        
                        constraints.append(ic_expr >= 0)
            
            # 5. Onward value约束（完全等价）
            for A in self.joint_actions_idx:
                for B in self.joint_actions_idx:
                    for ss in self.states_idx:
                        constraints.append(pi[A] == cp.sum(z[A, B, ss]))
            
            # 6. pi必须是有效分布（完全等价）
            constraints.append(cp.sum(pi) == 1)
            
            # 构建完全等价的可行性问题
            prob = cp.Problem(cp.Minimize(0), constraints)
            
            try:
                #prob.solve(solver=cp.ECOS, verbose=False)
                prob.solve(verbose=False)
                # 完全等价的求解结果处理逻辑
                if prob.status in [cp.OPTIMAL, cp.OPTIMAL_INACCURATE]:
                    # 完全等价的解提取逻辑
                    v_induced_val = v_induced.value
                    pi_val = VSI.trim_distribution(pi.value)
                    
                    w_val = np.empty((num_joint_actions, num_joint_actions, num_states), dtype=object)
                    for A, B, ss in itertools.product(self.joint_actions_idx, self.joint_actions_idx, self.states_idx):
                        w_val[A, B, ss] = z[A, B, ss].value @ VS[ss]
                        if pi_val[A] > 0:
                            w_val[A, B, ss] = w_val[A, B, ss] / pi_val[A]
                        else:
                            w_val[A, B, ss][:] = 0.0
                    
                    # 完全等价的调试输出
                    self.count_check_inducibility += 1
                    if prob.status == cp.OPTIMAL_INACCURATE:
                        print(f"check_inducibility ({self.count_check_inducibility}): FEASIBLE (approximate)...")
                    else:
                        print(f"check_inducibility ({self.count_check_inducibility}): FEASIBLE...")
                    results[k] = (True, CompactStrategy(pi_val, w_val, v_induced_val))
                elif prob.status in [cp.INFEASIBLE, cp.UNBOUNDED]:
                    # 完全等价的不可行处理
                    self.count_check_inducibility += 1
                    print(f"check_inducibility ({self.count_check_inducibility}): INFEASIBLE...")
                    results[k] = (False, None)
                else:
                    # 完全等价的错误处理
                    raise RuntimeError(f"check_inducibility failed: issues with LP. Status: {prob.status}")
            except Exception as e:
                # 完全等价的异常处理
                raise RuntimeError(f"check_inducibility failed: {e}")


        # 完全等价的返回逻辑
        if single_target_value:
            return results[0]
        else:
            return results

    """
    -----------------------------
    Correlated Bellman operator 
    -----------------------------
    """
    def CBO(self, VS = None, dense_mono=True, parallel=False):
        """
        Apply correlated Bellman operator (\hat{\Phi} in the paper) to VS

        :param VS: Value-set function to be processed. If None, CBO returns the bounding box as the init point of VSI
        :param dense_mono: True if: 1) VS includes all grid points in convex hull (not just vertices),
                    and 2) the new value sets are guaranteed to be subsets of VS
        :param parallel: Compute next_VS in parallel mode.
        """

        if VS is None: # If VS is None, initialize VS
            next_VS = [self.grid_points.copy() for _ in self.states_idx]
        else:
            bounds = VS  # Superset of next_VS
            if not dense_mono:
                bounds = [self.grid_points for _ in self.states_idx]

            next_VS = [None] * len(VS)
            if parallel:
                # --- Check inducibility in parallel ---
                inputs = [(VS, s, bounds[si]) for si, s in enumerate(self.states)]
                print(f"Begin checking inducibility ({sum(len(vs) for vs in bounds)} points)...")
                with Pool() as pool:
                    results = pool.starmap(self.check_inducibility, inputs)
                for si, _ in enumerate(self.states):
                    next_VS[si] = np.array(
                        [p for pi, p in enumerate(bounds[si]) if results[si][pi][0] is True]
                    )
            else:
                for si, s in enumerate(self.states):
                    results = self.check_inducibility(VS, s, bounds[si])
                    next_VS[si] = np.array([p for i, p in enumerate(bounds[si]) if results[i][0]])

            print(f"{sum(len(vs) for vs in next_VS)} points inducible.")
        return next_VS

    """
    --------------------------------
    Save value sets
    --------------------------------
    """
    def save_value_sets(self, VS, file_path, tag=""):
        """ Save value sets to disk """
        if file_path is None: return
        file = open(file_path, "a")

        for si in self.states_idx:
            if VS is None:
                file.write(f"{tag}, {si}" + "\n")
            else:
                for p in VS[si]:
                    file.write(f"{tag}, {si}, " + ", ".join(str(x) for x in p) + "\n")
        file.flush()

    """
    --------------------------------
    Construct inducible value sets
    --------------------------------
    """
    def construct_inducible_value_sets(self, file_path=None, parallel=False):
        """
        Run value-set iteration to compute inducible value sets.
        Save results in self.inducible_value_sets.

        :param file_path: If not None, save value sets in all iterations to file_path.
        :param parallel: Use parallel mode in CBO.
        """

        VS = self.CBO(None, parallel=parallel)  # Initialize value sets
        for t in itertools.count(1):  # Begin value-set iteration
            print(f"VSI iteration: {t}")
            next_VS = self.CBO(VS, parallel=parallel)

            if VSI.value_sets_identical(VS, next_VS):
                self.inducible_value_sets = VS
                return
            else:
                VS = next_VS
                self.save_value_sets(VS, file_path, t)

    """
    --------------------------------
    Find inducing strategy
    --------------------------------
    """
    def find_inducing_strategy(self, state, target_value):
        """
        Compute a strategy to induce target_value at state.
        :return: Inducing strategy in compact representation. None if target_value not inducible.
        """

        if self.inducible_value_sets is None:
            raise RuntimeError("Inducible value sets not constructed yet!")

        VS = self.inducible_value_sets
        inducible, strategy = self.check_inducibility(VS, state, target_value)

        if inducible: return strategy
        else: return None

    """
    --------------------------------
    Initialize policy
    --------------------------------
    """
    def init_policy(self, init_state, target_value):
        """
        Initialize a policy that yields target_value at init_state. Save it to self.policy.
        :return: The immediate joint action distribution.
        """
        self.history = [OneStepLog(None, None, init_state)]  # Initialize history
        self.policy = self.find_inducing_strategy(init_state, target_value)  # Policy same as the inducing strategy
        self.current_strategy = self.policy  # Initialize current strategy
        return self.current_strategy.pi

    """
    --------------------------------
    Initialize OPTIMAL policy
    --------------------------------
    """
    def init_optimal_policy(self, init_state, obj):
        """
        Initialize optimal policy using CVXPY (完全等价替换).
        """
        if self.inducible_value_sets is None:
            raise RuntimeError("Inducible value sets not constructed yet!")
        VS = self.inducible_value_sets

        # 计算关于obj的最优值（完全等价）
        si = self.states.index(init_state)
        vertices = VS[si]
        num_vertices = len(vertices)
        
        # 使用CVXPY构建完全等价的优化问题
        x = cp.Variable(num_vertices)
        
        # 完全等价的约束
        constraints = [
            x >= 0,  # 等价于lb=0
            x <= 1,  # 等价于ub=1
            cp.sum(x) == 1  # 等价于x.sum() == 1
        ]
        
        # 完全等价的目标函数
        objective = cp.Maximize(x @ vertices @ obj)
        
        prob = cp.Problem(objective, constraints)
        
        try:
            # prob.solve(solver=cp.ECOS)
            prob.solve()
            # 完全等价的求解结果处理
            if prob.status == cp.OPTIMAL:
                v = x.value @ vertices
                opt = prob.value
                
                # 完全等价的后续处理
                self.init_policy(init_state, v)
                return self.current_strategy.pi, opt
            else:
                # 完全等价的错误处理
                raise RuntimeError(f"Failed to compute optimal inducible value. Status: {prob.status}")
        except Exception as e:
            # 完全等价的异常处理
            raise RuntimeError(f"Failed to compute optimal inducible value: {e}")

    """
    --------------------------------
    New step
    --------------------------------
    """
    def new_step(self, joint_action_recommended, joint_action_played, state):
        """
        Update a new step, recording the joint action recommended, the joint action played, and the new state.
        :return: the next immediate joint action distribution.
        """
        if self.policy is None:
            raise RuntimeError("Policy not initialized!")

        A = self.joint_actions.index(joint_action_recommended)
        B = self.joint_actions.index(joint_action_played)
        s = self.states.index(state)
        v = self.current_strategy.w[A, B, s]

        new_strategy = self.find_inducing_strategy(state, v)
        self.current_strategy = new_strategy if new_strategy is not None else self.current_strategy
        self.history.append(OneStepLog(joint_action_recommended, joint_action_played, state))
        return self.current_strategy.pi
