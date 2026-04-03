import os
import pandas as pd
import numpy as np
from time import strftime
from MarkovGame import MarkovGame
from VSI_replace import VSI

# ------------------------------------------
# 步骤1：定义与原始游戏相同的参数
# ------------------------------------------
max_mushrooms = 16
max_slimes = 27
states = [(i, j) for i in range(max_mushrooms + 1) for j in range(max_slimes + 1)]
num_agents = 2
actions_per_agent = [["hunt", "clean"]] * num_agents

def reward_fn(s, A):
    num_mushrooms = s[0]
    num_hunters = A.count("hunt")
    rwd = np.zeros(num_agents)
    for i in range(num_agents):
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
    slime_threshold = 1

    num_mushrooms = max(num_mushrooms - num_hunters, 0) + mushroom_grow_rate * (num_slimes <= slime_threshold)
    num_mushrooms = min(num_mushrooms, max_mushrooms)
    num_slimes = max(num_slimes - num_cleaners * clean_rate, 0) + slime_grow_rate
    num_slimes = min(num_slimes, max_slimes)

    next_state = (num_mushrooms, num_slimes)
    prob = np.zeros(len(states))
    prob[states.index(next_state)] = 1
    return prob

# ------------------------------------------
# 步骤2：重建游戏对象和VSI对象
# ------------------------------------------
mg = MarkovGame.from_functions(states, actions_per_agent, trans_fn, reward_fn)
vsi = VSI(game=mg, gamma=2/3, delta=0.5, epsilon=0.5)

# ------------------------------------------
# 步骤3：读取并解析CSV文件
# ------------------------------------------
# 替换为您实际的CSV文件路径
csv_file_path = '/home/chengrm/work/multiagent/VSI/results/mushroom_20251229_115331.csv'

# 读取CSV文件
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
num_states = len(states)
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

# ------------------------------------------
# 步骤4：将值集加载到VSI对象
# ------------------------------------------
# 创建与状态数量匹配的列表
vsi.inducible_value_sets = [value_sets.get(i, np.array([])) for i in range(num_states)]

# ------------------------------------------
# 步骤5：计算最优策略
# ------------------------------------------
# 定义当前游戏状态（示例：初始状态）
current_state = (0, 0)

# 定义目标函数（例如，各agent权重相等）
objective = np.array([0.5, 0.5])

# 计算最优策略
try:
    pi, opt_value = vsi.init_optimal_policy(current_state, objective)
    print(f"最优值: {opt_value}")
    print(f"最优策略: {pi}")
    print(f"联合动作: {mg.joint_actions}")
    
    # 解释策略
    print("\n策略解释:")
    for i, action in enumerate(mg.joint_actions):
        print(f"动作 {action}: 概率 = {pi[i]:.4f}")
        
except Exception as e:
    print(f"计算最优策略时出错: {e}")

# ------------------------------------------
# 可选：执行策略示例
# ------------------------------------------
print("\n执行策略示例（10步）:")
rng = np.random.default_rng()
s = current_state
pi, _ = vsi.init_optimal_policy(s, objective)

for t in range(10):
    # 根据策略选择动作
    A_idx = rng.choice(len(pi), p=pi)
    A = mg.joint_actions[A_idx]
    
    # 采样下一状态
    s_new = mg.sample_next_state(s, A)
    
    # 获取下一状态的策略
    #上一个推荐动作+上次实际执行的动作+现在状态
    pi_new = vsi.new_step(A, A, s_new)
    
    # 计算当前步骤的奖励
    reward = mg.R_agents(s, A)
    
    print(f"步骤 {t}: 状态={s}, 动作={A}, 奖励={reward}, 下一状态={s_new}")
    
    # 更新状态和策略
    s = s_new
    pi = pi_new