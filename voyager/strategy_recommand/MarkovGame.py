from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence, Tuple, List, Callable, Dict
import itertools
import numpy as np
from numpy.typing import NDArray


@dataclass
class MarkovGame:
    """
    Tabular Markov game (stochastic game) in explicit tensor form.

    Shapes:
      S = #states, N = #agents, A = #joint actions = prod(|A_i|)
      P: (S, A, S)            transition probabilities
      R: (N, S, A)            rewards per agent
    """
    states: Sequence
    actions_per_agent: Sequence[Sequence]
    P: NDArray[np.float64]  # (S, A, S)
    R: NDArray[np.float64]  # (N, S, A)

    # --- computed after init ---
    num_agents: int = 0
    joint_actions: List[Tuple] = None
    # state_to_idx: Dict = None
    # action_to_idx: List[Dict] = None

    def __post_init__(self):
        self.states = list(self.states)
        # self.state_to_idx = {s: i for i, s in enumerate(self.states)}
        self.num_agents = len(self.actions_per_agent)
        self.actions_per_agent = [list(a) for a in self.actions_per_agent]
        # self.action_to_idx = [{a: i for i, a in enumerate(actions)} for actions in self.actions_per_agent]
        self.joint_actions = list(itertools.product(*self.actions_per_agent))

        self.P = np.asarray(self.P, dtype=float)
        self.R = np.asarray(self.R, dtype=float)

        S, A, N = len(self.states), len(self.joint_actions), self.num_agents

        if self.P.shape != (S, A, S):
            raise ValueError(f"P must have shape (S,A,S)={(S, A, S)}, got {self.P.shape}")
        if self.R.shape != (N, S, A):
            raise ValueError(f"R must have shape (N,S,A)={(N, S, A)}, got {self.R.shape}")
        # probability sanity
        if not np.allclose(self.P.sum(axis=2), 1.0, atol=1e-10):
            raise ValueError("Each row P[s, a, :] must sum to 1.")
        if (self.P < -1e-12).any():
            raise ValueError("P has negative entries.")

    # ---------- helpers ----------
    def joint_index(self, a_joint: Tuple) -> int:
        """Map a tuple of per-agent actions to joint action index."""
        # try:
        return self.joint_actions.index(a_joint)
        # except ValueError:
        #     # allow labels: convert via per-agent maps if needed
        #     idxs = tuple(self.action_to_idx[i][a_joint[i]] for i in range(self.num_agents))
        #     # rebuild normalized label tuple in same order as joint_actions
        #     label_tuple = tuple(self.actions_per_agent[i][idxs[i]] for i in range(self.num_agents))
        #     return self.joint_actions.index(label_tuple)

    def R_agents(self, s, a_joint: Tuple) -> NDArray[np.float64]:
        """Return reward vector r_i(s,a) for all agents, shape (N,)."""
        si = self.states.index(s)
        ai = self.joint_index(a_joint)
        return self.R[:, si, ai]

    def P_row(self, s, a_joint: Tuple) -> NDArray[np.float64]:
        """Return P(s' | s, a), shape (S,)."""
        si = self.states.index(s)
        ai = self.joint_index(a_joint)
        return self.P[si, ai, :]

    def sample_next_state(self, s, a_joint: Tuple, rng: np.random.Generator | None = None):
        """Sample s' given state s and joint action a_joint."""
        if rng is None:
            rng = np.random.default_rng()
        p = self.P_row(s, a_joint)
        s_prime_idx = rng.choice(len(self.states), p=p)
        s_prime = self.states[s_prime_idx]
        return s_prime

    # ---------- build from functions ----------
    @classmethod
    def from_functions(
            cls,
            states: Sequence,
            actions_per_agent: Sequence[Sequence],
            trans_fn: Callable[[object, Tuple], NDArray[np.float64]],  # (s, a_joint) -> s' probs
            reward_fn: Callable[[object, Tuple], NDArray[np.float64]],  # (s, a_joint) -> r vector
    ) -> "MarkovGame":
        """Materialize P,R by enumerating (s, joint a) using user functions."""
        states = list(states)
        joint_actions = list(itertools.product(*actions_per_agent))
        S, A, k = len(states), len(joint_actions), len(actions_per_agent)
        P = np.zeros((S, A, S), dtype=float)
        R = np.zeros((k, S, A), dtype=float)

        for si, s in enumerate(states):
            for ai, a in enumerate(joint_actions):
                P[si, ai, :] = np.asarray(trans_fn(s, a), dtype=float).ravel()
                R[:, si, ai] = np.asarray(reward_fn(s, a), dtype=float).ravel()
                # if p.shape != (S,):
                #     raise ValueError(f"trans_fn must return shape ({S},), got {p.shape}")
                # P[si, ai, :] = p / p.sum()  # normalize defensively
                # for i in range(k):
                #     R[i, si, ai] = float(reward_fn(i, s, a))
        return cls(states, actions_per_agent, P, R)

    # # ---------- evaluate a fixed joint policy π(a|s) ----------
    # def evaluate_joint_policy(
    #         self,
    #         pi: NDArray[np.float64],
    #         gamma: float,
    # ) -> NDArray[np.float64]:
    #     """
    #     Evaluate a *state-dependent distribution over joint actions* π(a|s).
    #     pi shape: (S, A) with rows summing to 1.
    #     Returns V for all agents: shape (N, S).
    #     Solves (I - γ P_π) V_i = r_{π,i} for each agent i.
    #     """
    #     S = len(self.states)
    #     A = len(self.joint_actions)
    #     pi = np.asarray(pi, dtype=float)
    #     if pi.shape != (S, A):
    #         raise ValueError(f"pi must have shape (S,A)=({S},{A}), got {pi.shape}")
    #     if not np.allclose(pi.sum(axis=1), 1.0, atol=1e-10):
    #         raise ValueError("Each row of pi must sum to 1.")
    #
    #     # P_π: (S,S)
    #     P_pi = (self.P * pi[:, :, None]).sum(axis=1)
    #     I = np.eye(S)
    #     # r_{π,i}: (S,) for each i
    #     R_pi = (self.R * pi[None, :, :]).sum(axis=2)  # (N,S)
    #     # Solve per agent
    #     V = np.empty((self.num_agents, S), dtype=float)
    #     A_mat = I - gamma * P_pi
    #     for i in range(self.num_agents):
    #         V[i] = np.linalg.solve(A_mat, R_pi[i])
    #     return V
