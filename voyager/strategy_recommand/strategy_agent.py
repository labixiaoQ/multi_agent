import os
import pandas as pd
import numpy as np
from time import strftime
# from MarkovGame import MarkovGame
from voyager.strategy_recommand.MarkovGame import MarkovGame
from voyager.strategy_recommand.VSI_replace import VSI
# from VSI_replace import VSI

class MushroomStrategy:
    def __init__(self, max_mushrooms=16, max_slimes=27, gamma=2/3, delta=0.5, epsilon=0.5):
        """
        初始化蘑菇游戏VSI加载器，与原代码参数完全一致
        """
        self.max_mushrooms = max_mushrooms
        self.max_slimes = max_slimes
        self.gamma = gamma
        self.delta = delta
        self.epsilon = epsilon
        
        # 步骤1：定义与原始游戏相同的参数
        self.states = [(i, j) for i in range(self.max_mushrooms + 1) for j in range(self.max_slimes + 1)]
        self.num_agents = 2
        self.actions_per_agent = [["hunt", "clean"]]  * self.num_agents
        
        # 步骤2：重建游戏对象和VSI对象
        self.mg, self.vsi = self._rebuild_game_objects()
    
    def _rebuild_game_objects(self):
        """
        重建游戏对象和VSI对象，与原代码逻辑完全相同
        """
        def reward_fn(s, A):
            num_mushrooms = s[0]
            num_hunters = A.count("hunt")
            rwd = np.zeros(self.num_agents)
            for i in range(self.num_agents):
                rwd[i] = min(num_mushrooms/num_hunters, 1) if A[i] == "hunt" else 0
            return rwd

        def trans_fn(s, A):
            num_mushrooms = s[0]
            num_slimes = s[1]
            num_hunters = A.count("hunt")
            num_cleaners = A.count("clean")

            mushroom_grow_rate = 1
            slime_grow_rate = 1
            clean_rate = 1
            slime_threshold = 5

            num_mushrooms = max(num_mushrooms - num_hunters, 0) + mushroom_grow_rate * (num_slimes <= slime_threshold)
            num_mushrooms = min(num_mushrooms, self.max_mushrooms)
            num_slimes = max(num_slimes - num_cleaners * clean_rate, 0) + slime_grow_rate
            num_slimes = min(num_slimes, self.max_slimes)

            next_state = (num_mushrooms, num_slimes)
            prob = np.zeros(len(self.states))
            prob[self.states.index(next_state)] = 1
            return prob
        
        mg = MarkovGame.from_functions(self.states, self.actions_per_agent, trans_fn, reward_fn)
        vsi = VSI(game=mg, gamma=self.gamma, delta=self.delta, epsilon=self.epsilon)
        return mg, vsi
    
    def load_value_sets_from_csv(self, csv_file_path='/home/chengrm/work/multiagent/VSI/results/mushroom_20251229_115331.csv'):
        """
        从CSV文件加载值集，与原代码解析逻辑完全相同
        """
        # 读取CSV文件
        print(f"Loading value sets from {csv_file_path}")
        df = pd.read_csv(csv_file_path, header=None)
        # 确定值的数量（假设是2个agent）
        num_values = df.shape[1] - 2  # 减去iteration和state_index
        # 命名列
        columns = ['iteration', 'state_index'] + [f'value{i}' for i in range(num_values)]
        df.columns = columns

        # 获取最终迭代的值集（最大迭代次数）
        max_iteration = df['iteration'].max()
        final_values = df[df['iteration'] == max_iteration]

        # 按状态分组
        value_sets = {}
        num_states = len(self.states)
        for state_idx in range(num_states):
            # 提取该状态的所有值点
            state_df = final_values[final_values['state_index'] == state_idx]
            if not state_df.empty:
                # 获取值列
                value_columns = [f'value{i}' for i in range(num_values)]
                state_values = state_df[value_columns].values
                value_sets[state_idx] = state_values
            else:
                # 如果该状态没有值点，使用空数组
                value_sets[state_idx] = np.array([])

        # 将值集加载到VSI对象
        self.vsi.inducible_value_sets = [value_sets.get(i, np.array([])) for i in range(num_states)]
        
        return value_sets
    
    def compute_optimal_policy(self, current_state=(0, 0), objective=np.array([0.5, 0.5])):
        """
        计算最优策略，与原代码逻辑完全相同
        """
        try:
            pi, opt_value = self.vsi.init_optimal_policy(current_state, objective)
            print(f"最优值: {opt_value}")
            print(f"最优策略: {pi}")
            print(f"联合动作: {self.mg.joint_actions}")
            
            # 解释策略
            print("\n策略解释:")
            for i, action in enumerate(self.mg.joint_actions):
                print(f"动作 {action}: 概率 = {pi[i]:.4f}")
                
            return pi, opt_value
        except Exception as e:
            print(f"计算最优策略时出错: {e}")
            return None, None
    
    def execute_policy(self, current_state=(0, 0), objective=np.array([0.5, 0.5]), num_steps=5):
        """
        执行策略示例，与原代码逻辑完全相同
        """
        print(f"\n执行策略示例（{num_steps}步）:")
        rng = np.random.default_rng()
        s = current_state
        pi, _ = self.vsi.init_optimal_policy(s, objective)

        for t in range(num_steps):
            # 根据策略选择动作
            A_idx = rng.choice(len(pi), p=pi)
            A = self.mg.joint_actions[A_idx]
            
            # 采样下一状态
            s_new = self.mg.sample_next_state(s, A)
            
            # 获取下一状态的策略
            pi_new = self.vsi.new_step(A, A, s_new)
            
            # 计算当前步骤的奖励
            reward = self.mg.R_agents(s, A)
            
            print(f"步骤 {t}: 状态={s}, 动作={A}, 奖励={reward}, 下一状态={s_new}")
            
            # 更新状态和策略
            s = s_new
            pi = pi_new
    def recommend_strategy(self, current_state=(0, 0), current_policy=None, current_policy_player=None, num_steps=5):
        print(f"\n执行策略示例（{num_steps}步）:")
        rng = np.random.default_rng()
        s = current_state
        objective = np.array([0.5, 0.5])
        pi, _ = self.vsi.init_optimal_policy(s, objective)
        
        
        #上一个推荐动作+上次实际执行的动作+现在状态-》下一个推荐策略
        pi_new = self.vsi.new_step(current_policy, current_policy_player, current_state)
        index_max = np.argmax(pi_new)
        next_policy_player = self.mg.joint_actions[index_max]
        reward = self.mg.R_agents(s, current_policy_player)
        print(f"步骤: 状态={s}, 实际执行的动作={current_policy_player}, 下一步推荐的动作={next_policy_player}, 奖励={reward}")
        return next_policy_player




# # 主函数示例 - 与原代码执行逻辑完全相同
# if __name__ == "__main__":
#     # 创建加载器实例
#     loader = MushroomGameVSILoader()
    
#     # 加载值集
#     loader.load_value_sets_from_csv()
    
#     # 计算最优策略
#     current_state = (0, 0)
#     objective = np.array([0.5, 0.5])
#     loader.compute_optimal_policy(current_state, objective)
    
#     # 执行策略示例
#     loader.execute_policy(current_state, objective, num_steps=5)