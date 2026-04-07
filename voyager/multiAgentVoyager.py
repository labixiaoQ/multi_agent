import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
import concurrent.futures
from voyager import Voyager
from voyager.negotiation import Negotiation, Negotiator
from voyager.strategy_recommand.strategy_agent import MushroomStrategy
import time
import voyager.utils as U
import copy
from datetime import datetime
import random
import requests
import re

from dataclasses import dataclass

@dataclass
class AgentState:
    real_strategy_count: int = 0
    current_strategy: tuple = None
    real_strategy: tuple = None
    real_state: tuple = (18, 11)
    recommend_strategy: tuple = None



class MultiAgentVoyager:
    
    def __init__(self, 
        num_agents=2, 
        server_port=3003,
        usernames=["Gizmo", "Glitch"],  
        judge_username="Judy",
        scenario_file=None,
        save_dir=None, 
        critic_mode="auto", 
        contract_mode="auto",
        contract=None,
        continuous=True,
        episode_timeout=200, #120
        num_episodes=3,
        negotiator_model_name="gpt-3.5-turbo",
        negotiator_temperature=0.7,
        #negotiator_model_api_base="https://api.openai.com/v1",
        skinurls = [
            "https://images2.imgbox.com/60/3d/2bJnlM8U_o.png", # player 1 skin
            "https://images2.imgbox.com/a7/6c/hZRGGRAS_o.png" # player 2 skin
        ],
        options={},
        action_agent_show_strategy: bool = True,
        #### 新增
        strategy_timeout = 180,
        total_strategy_count = 1,
        strategy_history = [],
        recommend_strategy_history = [],
        state_history = [],
        timeout_history = [],
        total_time_limit = 60,

        # strategy = None,
        # ####
    ):
        # Strategy management
        self.strategy_lock = threading.Lock()
        self.strategy_queues = {}  # One queue per agent
        self.active_strategies = {}  # Currently active strategies
        self.strategy_timeout = strategy_timeout
        self.total_strategy_count = total_strategy_count
        self.strategy_history = strategy_history 
        self.recommend_strategy_history = recommend_strategy_history
        self.timeout_history = timeout_history
        self.state_history = state_history
        self.max_mushrooms = 18
        self.max_slimes = 11
        self.strategy = MushroomStrategy(max_mushrooms=self.max_mushrooms, max_slimes=self.max_slimes, gamma=2/3, delta=0.5, epsilon=0.5)
        self.csv_file_path = "/Users/chengrenmin/work/multiagent/Voyager-Contracts/result/mushroom_20260104_160922.csv"
        self.total_event = []
        self.total_time_limit = total_time_limit  # 新增：保存总时间限制

        # 将 show_strategy 标志注入 options，透传给 Voyager → ActionAgent
        options = dict(options)  # 避免修改调用方传入的原始 dict
        options['action_agent_show_strategy'] = action_agent_show_strategy

        self.scenario_file = scenario_file
        self.scenario_description = None
        self.scenario_code = None
        self.critic_mode = critic_mode
        self.continuous = continuous
        self.contract_mode = contract_mode
        self.contract = contract
        self.agents = []
        self.judge = None
        self.usernames = usernames
        self.judge_username = judge_username
        self.num_episodes = num_episodes
        self.negotiator_model_name = negotiator_model_name
        self.negotiator_temperature = negotiator_temperature
        #self.negotiator_model_api_base = negotiator_model_api_base
        self.skinurls = skinurls
        self.chest_memory = {}
        self.episode = 0
        self.load_from_save = False
        self.reward_item_names = None

        assert critic_mode in ["auto", "manual"]
        assert contract_mode in ["auto", "manual"]
        if self.continuous:
            assert isinstance(self.num_episodes, int) and self.num_episodes > 0

        if self.contract_mode == "manual":
            if contract is None:
                raise ValueError("Contract mode is manual but no contract was provided")
            if not isinstance(contract, str):
                raise ValueError("Contract must be a string")
            self.contract = contract        

        if num_agents != 2:
            raise ValueError("Only 2 agents are supported at this time")
        
        # load game save directory if it exists
        if save_dir is not None and U.f_not_empty(save_dir):
            print("Provided save directory exists. Loading game...")
            self.save_dir = save_dir

            # recover contract
            try:
                with open(f"{self.save_dir}/contract.txt", 'r') as contract_file:
                        self.contract = contract_file.read()
                if contract_mode == "auto":
                    print("Warning: contract mode is auto but contract was found in save directory. Overwriting with saved contract...")
            except FileNotFoundError:
                raise Exception("No contract found in save directory")
            
            self.load_from_save = True
        
        # create new game save directory
        else:
            if save_dir is None:
                self.save_dir = f"saves/game_save_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            else:
                self.save_dir = save_dir
            U.f_mkdir(self.save_dir)
            U.f_mkdir(f"{self.save_dir}/episodes")

        # create judge
        self.judge = Voyager(
            server_port=server_port,
            username=self.judge_username,
            ckpt_dir=f"{self.save_dir}/{self.judge_username}_ckpt",
            episode_timeout=episode_timeout,
            **options
        )
        self.judge.env.reset()
        self.judge.heartbeat_interval = 10
        self.connection_timeout = 10


        # create agents with fixed port allocation to avoid conflicts
        # Use fixed port offsets for each agent to ensure stability
        port_offsets = {
            'Gizmo': 10,
            'Glitch': 20,
            'Judy': 25
        }
        
        for i in range(num_agents):
            username = self.usernames[i]
            ckpt_dir = f"{self.save_dir}/{username}_ckpt"
            
            # Use fixed port offset instead of random
            agent_port = server_port + port_offsets.get(username, (i + 1) * 10)
            print(f"Creating agent {username} on port {agent_port}")
            
            agent = Voyager(
                username=username,
                server_port=str(agent_port),
                ckpt_dir=ckpt_dir,
                episode_timeout=episode_timeout,
                **options
            )
            
            # Wait for agent server to start before proceeding
            self._wait_for_server_ready(agent_port)
            self.agents.append(agent)
            
            # Add delay between agent creations to avoid resource conflicts
            if i < num_agents - 1:
                print(f"Waiting 3 seconds before creating next agent...")
                time.sleep(3)

        # set voyager skins
        for i, agent in enumerate(self.agents):
            agent.env.reset()
            agent.env.step(
                U.skins_commands(self.skinurls[i])
        )

        time.sleep(2)  # Additional wait time for stability

    def _wait_for_server_ready(self, port, max_retries=15, timeout=10):
        """Wait for the server on the specified port to be ready"""
        import requests
        import time
        
        server_url = f"http://127.0.0.1:{port}"
        for retry in range(max_retries):
            try:
                # Try to connect to the server with a simple GET request
                # Use a small timeout to avoid blocking too long
                response = requests.get(server_url, timeout=2)
                # If we get any response (even 404), the server is running
                print(f"Server on port {port} is ready")
                return True
            except requests.exceptions.ConnectionError:
                if retry % 3 == 0:  # Only log every 3rd attempt to reduce noise
                    print(f"Server on port {port} not ready yet (attempt {retry + 1}/{max_retries})")
                time.sleep(2)  # Longer wait time for server startup
            except requests.exceptions.RequestException as e:
                if retry % 3 == 0:
                    print(f"Error checking server on port {port}: {e}")
                time.sleep(2)
        
        print(f"Warning: Server on port {port} may not be ready after {max_retries} attempts")
        # Even if not ready, continue and let the normal error handling deal with it
        return True

    def run_threads(self, target, args=None, include_judge=False, shared_args=False):
        """
        Runs target function in parallel for each agent. args is a dictionary of arguments to pass to each thread, where the key is the agent's username.

        For example,
        args = {'Voyager3000': {'arg1': 1, 'arg2': 2}, 'Voyager3001': {'arg1': 3, 'arg2': 4}}
        """
        agents = self.agents + [self.judge] if include_judge else self.agents
        if args is None: args = {agent.username: {} for agent in agents}
        if shared_args: args = {agent.username: args for agent in agents}

        results = {}
        threads = []
        for agent in agents:
            result = {}
            thread = threading.Thread(target=target, args=(agent, result), kwargs=args[agent.username], daemon=True)
            results[agent.username] = result
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        return results
    
    def run_threads_non_blocking(self, target, args=None, include_judge=False, shared_args=False, timeout=30, round_num=0):
       
        agents = self.agents + [self.judge] if include_judge else self.agents
        if args is None: args = {agent.username: {} for agent in agents}
        if shared_args: args = {agent.username: args for agent in agents}

        results = {agent.username: {} for agent in agents}
        
        # 验证 args 结构，确保所有必需参数都存在
        print(f"=== Validating args for Round {round_num} ===")
        for agent in agents:
            agent_args = args.get(agent.username, {})
            print(f"  {agent.username}: {list(agent_args.keys())}")
            # 如果缺少关键参数，记录警告
            if not agent_args:
                print(f"  ⚠ WARNING: Empty args for {agent.username}")
        
        # 包装target函数以增强错误处理
        def wrapped_target(agent, **kwargs):
            result = {}
            try:
                target(agent, result, **kwargs)
            except TypeError as e:
                print(f"TypeError in thread {agent.username}_round{round_num}: {e}")
                print(f"  Kwargs received: {list(kwargs.keys())}")
                import traceback
                traceback.print_exc()
            except Exception as e:
                print(f"Error in thread {agent.username}_round{round_num}: {e}")
                import traceback
                traceback.print_exc()
                # 确保agent的环境仍然可用
                if hasattr(agent, 'env') and hasattr(agent.env, 'check_process'):
                    try:
                        agent.env.check_process()
                    except Exception as env_e:
                        print(f"Failed to check/restore agent environment: {env_e}")
            return agent.username, result
        
        # 使用线程池执行
        print(f"=== Starting Round {round_num} with ThreadPoolExecutor (timeout={timeout}s) ===")
        executor = ThreadPoolExecutor(max_workers=len(agents), thread_name_prefix=f"round{round_num}")
        
        try:
            # 提交所有任务
            futures = {
                executor.submit(wrapped_target, agent, **args[agent.username]): agent.username 
                for agent in agents
            }
            
            # 等待所有任务完成，带超时
            try:
                done, not_done = wait(
                    futures.keys(),
                    timeout=timeout,
                    return_when=concurrent.futures.ALL_COMPLETED
                )
                
                # 收集已完成任务的结果
                for future in done:
                    try:
                        username, result = future.result(timeout=1)
                        results[username] = result
                        print(f"✓ Task completed for {username}")
                    except Exception as e:
                        username = futures[future]
                        print(f"✗ Error getting result for {username}: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 处理超时的任务
                if not_done:
                    print(f"\n⚠ WARNING: {len(not_done)} task(s) timed out after {timeout}s")
                    for future in not_done:
                        username = futures[future]
                        print(f"  - Task timeout: {username}")
                        # 尝试取消未完成的任务
                        cancelled = future.cancel()
                        if not cancelled:
                            print(f"  - Could not cancel {username}, task may still be running")
                        
            except Exception as e:
                print(f"❌ ThreadPool execution error: {e}")
                import traceback
                traceback.print_exc()
                
        finally:
            # 强制关闭线程池，不等待未完成的任务
            print(f"Shutting down executor for round {round_num}...")
            executor.shutdown(wait=False)  # 不等待，强制关闭
            print(f"=== Round {round_num} executor shutdown complete ===\n")
        
        return results
    
    def reset_agents(self, mode='soft', timeout=20):
        args = {agent.username: {'options': {'mode': mode, 'wait_ticks': agent.env_wait_ticks}} for agent in self.agents}
        self.run_threads(lambda agent, _, options: agent.env.reset(options=options), args=args)
        time.sleep(2)

    def pause_agents(self):
         for agent in [self.judge] + self.agents:
            if agent.env is not None:
                agent.env.pause()
            print('Pausing agents...')
            break #pause one agent = pause all agents

    def unpause_agents(self):
         for agent in [self.judge] + self.agents:
            if agent.env is not None:
                agent.env.unpause()
            print('Unpausing agents...')
            break



    def save_scenario(self, save_options):
        """
        Saves the current scenario to a json file. The scenario is saved as a dictionary with the following keys:
        - block_positions: a dictionary of block types and their positions
        - spawn_locations: a dictionary of agent usernames and their spawn locations
        - chest_contents: a string of the chest contents in minecraft format
        """
        print('Saving scenario...')

        if len(self.agents) == 0:
            raise('At least one agent must be initialized to save scenario')

        scenario_block_types = save_options['scenario_block_types']
        file_name = save_options['file_name']
        center_position = save_options['center_position']
        remove_blocks = save_options['remove_blocks']

        # set file_name
        if self.scenario_file != file_name:
            print(f'Warning: scenario_file does not match file_name, using {file_name}')
        file_name = "scenarios/" + file_name

        def extract_block_positions(events):
            block_types = scenario_block_types
            block_positions = {block: [] for block in block_types}

            for event in events:
                if event[0] == 'onChat':
                    message = event[1]['onChat']
                    # Checking each block type
                    for block in block_types:
                        if block in message:
                            # Extracting positions
                            positions = message.split(f'{block}: ')[-1].replace('),(', ');(').split(';')
                            for pos in positions:
                                if not pos.strip():  # Check if the position is an empty string
                                    continue
                                x, y, z = map(int, pos.strip('()').split(', '))
                                coord_dict = {'x': x, 'y': y, 'z': z}  # Convert coords to dictionary format
                                block_positions[block].append(coord_dict)

            # Removing block types with no positions found
            block_positions = {k: v for k, v in block_positions.items() if v}
            return block_positions

        # self.judge.env.reset(
        #         options={
        #             "mode": "hard",
        #             "wait_ticks": self.judge.env_wait_ticks,
        #         }
        #     )
        
        x, y, z = center_position['x'], center_position['y'], center_position['z']

        # Remove blocks of type scenario_block_types so they don't interfere with the scenario
        if remove_blocks:
            input(f"Center position is set to {center_position}. Blocks of type {scenario_block_types} will be deleted nearby. Press enter to continue...")
            print("Removing blocks...\n")
            self.judge.env.step(
                f"await bot.chat('/tp {x} {y} {z}');"
                + U.remove_blocks_commands(scenario_block_types, center_position),
                programs=self.judge.skill_manager.programs,
            )

        # Save blocks of type scenario_block_types
        input(f"Construct the scenario. Blocks of type {scenario_block_types} will be saved. Press enter when done...")
        print("Saving blocks...\n")
        events = self.judge.env.step(
            f"bot.chat('/tp {x} {y} {z}');"
            + f"await getBlockPositions(bot, {U.json_dumps(scenario_block_types)}, {U.json_dumps(center_position)})", # should be able to specify center square of save area
            programs=self.judge.skill_manager.programs,
        )

        block_positions = extract_block_positions(events)

        # save block_positions as well as default spawn locations and chest contents
        json_contents = {
            'description': 'There is a chest with a diamond pickaxe.',
            'secret_description': 'Agents do not see this description, just for information',
            'tasks': {self.usernames[0]: 'mine diamond', self.usernames[1]: 'mine iron'},
            'center_position': center_position,
            'block_positions': {'facing': 'north', **block_positions},
            'spawn_locations': {self.usernames[0]: {'x':x+1, 'y': y, 'z': z+1}, self.usernames[1]: {'x':x-1, 'y': y, 'z': z-1}},
            'reward_item_name': ['diamond'],
            'chest_contents': {'diamond_pickaxe':1},
        }
        U.custom_dump(json_contents, file_name)
        print('Scenario saved in ', file_name)
        self.judge.close()

    def load_scenario(self, reset='soft'):

        # set file_name
        file_name = "scenarios/" + self.scenario_file

        try: 
            json_contents = U.json_load(file_name)
            print(f'Loading {self.scenario_file}...')
        except FileNotFoundError:
            raise('No scenario file found')

        self.scenario_description = json_contents['description']
        tasks = json_contents['tasks']
        center_position = json_contents['center_position']
        block_positions = json_contents['block_positions']
        spawn_locations = json_contents['spawn_locations']
        chest_contents = U.parse_chest_contents(json_contents['chest_contents'])
        self.reward_item_names = json_contents['reward_item_names']
        scenario_block_types = list(block_positions.keys())
        scenario_block_types.remove('facing')
        self.chest_memory = {}

        # set agent tasks
        for i, agent in enumerate(self.agents):
            agent.task = tasks[agent.username]

        # set judge task to all agents tasks
        self.judge.task = tasks

        # if .js with same filename exists, load it
        if U.f_exists(file_name.replace('.json', '.js')):
            self.scenario_code = U.load_text(file_name.replace('.json', '.js'))
        else:
            print('Warning: No scenario code file found')

        # clear inventory for both agents
        if len(self.agents) == 0:
            raise('At least one agent must be initialized to load scenario')
        self.reset_agents(mode='hard')

        x, y, z = center_position['x'], center_position['y'], center_position['z']

        # spawn bots, replace blocks, and fill chest
        self.judge.env.step(
            f"bot.chat('/gamemode spectator {self.judge_username}');"
            + f"bot.chat('/tp {self.judge_username} {x} {y+20} {z}');" # move this into a helper?
            + f"bot.chat('/gamerule randomTickSpeed 3');"
            + f"bot.chat('/gamerule spawnRadius 0');"
            + U.remove_drops_commands()
            + (U.remove_blocks_commands(scenario_block_types, center_position) if reset == 'hard' else '')
            + U.spawn_commands(self.usernames, spawn_locations)
            + U.add_block_commands(block_positions)
            + U.chest_commands(block_positions, chest_contents),
            programs=self.judge.skill_manager.programs,
        )
        # events[-1][1]["inventory"] = new_events[-1][1]["inventory"]
        # events[-1][1]["voxels"] = new_events[-1][1]["voxels"]

        if self.scenario_code is not None:
            self.judge.env.step(self.scenario_code)

    # update a global chest memory to keep consistent across agents
    def update_chest_memory(self, chests):
        for position, chest in chests.items():
            if position in self.chest_memory:
                if isinstance(chest, dict):
                    self.chest_memory[position] = chest
                if chest == "Invalid":
                    print(
                        f"\033[32mRemoving chest {position}: {chest}\033[0m"
                    )
                    self.chest_memory.pop(position)
            else:
                if chest != "Invalid":
                    print(f"\033[32mSaving chest {position}: {chest}\033[0m")
                    self.chest_memory[position] = chest

        # update agent chest memories
        for agent in self.agents + [self.judge]:
            agent.action_agent.chest_memory = self.chest_memory

    def check_task_success(self, events, max_retries=5):
        
        def ai_check_task_success(agent, result, events):
            if agent.username == self.judge_username:
                critic_agent = agent.judge_agent
            else:
                critic_agent = agent.critic_agent

            human_message = critic_agent.render_human_message(
                events=events,
                task=agent.task,
                scenario=self.scenario_description,
                contract=self.contract,
                context=agent.context,
                chest_observation=agent.action_agent.render_chest_observation(),
            )
            messages = [
                critic_agent.render_system_message(),
                human_message,
            ]
            critic_response = critic_agent.ai_check_task_success(
                messages=messages, max_retries=max_retries
            )

            if agent.username == self.judge_username:
                emeralds, critique = critic_response
                success = None
            else:
                success, critique = critic_response
                emeralds = None

            result.update({'success': success, 'critique': critique, 'emeralds': emeralds})
        
        # TODO: include judge human feedback
        def human_check_task_success():
            results = {agent.username: {} for agent in self.agents}
            # log critic human critic messages
            for agent in self.agents:
                agent.critic_agent.render_human_message(
                    events=events[agent.username]['events'],
                    task=agent.task,
                    scenario=self.scenario_description,
                    contract=self.contract,
                    context=agent.context,
                    chest_observation=agent.action_agent.render_chest_observation(),
                )
            # collect critiques about agents
            for agent in self.agents:
                confirmed = False
                success = False
                critique = ""
                while not confirmed:
                    success = input(f"{agent.username} Success? (y/n)")
                    success = success.lower() == "y"
                    critique = input("Enter your critique:")
                    print(f"Success: {success}\nCritique: {critique}")
                    confirmed = input("Confirm? (y/n)") in ["y", ""]
                results[agent.username].update({'success': success, 'critique': critique})
            return results

        if self.critic_mode == "manual":
            return human_check_task_success()
        
        critic_responses = self.run_threads(ai_check_task_success, events, include_judge=True)
        # Transform responses into expected format
        formatted_responses = {}
        for agent in self.agents + [self.judge]:
            formatted_responses[agent.username] = {
                'success': critic_responses[agent.username]['success'],
                'critique': critic_responses[agent.username]['critique'],
                'emeralds': critic_responses[agent.username]['emeralds']
            }
            print(f"{agent.username} - Success: {formatted_responses[agent.username]['success']}, Emeralds: {formatted_responses[agent.username]['emeralds']}")
        return formatted_responses
        
    def summary_subtask(self,chat_log):
        """Summarizes the subtask from the events"""
        def ai_summary_subtask(result, chat_log):   

            print("Summarizing subtask")         

            events_str = ""
            slime_count = 0
            mushroom_count = 0
            pattern_slime = r"setblock_slime_block\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)"
            pattern_mushroom = r"setblock_red_mushroom_block\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)"
            #列表转字符串
            chat_log = "".join(chat_log)
            
            matches_slime = re.findall(pattern_slime, chat_log)
            matches_mushroom = re.findall(pattern_mushroom, chat_log)
            #统计slime和mushroom的数量
            slime_count = len(matches_slime)
            mushroom_count = len(matches_mushroom)
            print(f"Slime block placements found: {slime_count}, Mushroom block placements found: {mushroom_count}")

            # pattern_hunt = r"collect_mushrooms"
            # pattern_clean = r"clean_slime"
            # matches_hunt = re.findall(pattern_hunt, events_str)
            # matches_clean = re.findall(pattern_clean, events_str)

            # #统计受伤和清洁slime的次数
            # hunt_count = len(matches_hunt)
            # clean_count = len(matches_clean)
            # print(f"hunt mushrooms count: {hunt_count}, Clean slime count: {clean_count}")
           
            # print(f"Combined events string: {events_str}")
            pattern = r"Waste blocks count: (\d+), Reward blocks count: (\d+)"
            matches = re.findall(pattern, chat_log)
            # print(f"chat_log: {chat_log}")
            print(f"匹配结果: {matches}")
            
            if matches:
                # 获取最后一个匹配项
                last_match = matches[-1]
                print(f"最后一处匹配内容: {last_match}")
                waste_blocks = int(last_match[0])
                reward_blocks = int(last_match[1])
                print(f"最后一处匹配内容: Waste blocks count: {waste_blocks}, Reward blocks count: {reward_blocks}")
                print(f"Slime block placements found: {slime_count}, Mushroom block placements found: {mushroom_count}")
                print(f"上次的状态记录: {self.state_history[-1] if self.state_history else '无'}")
               
                # 记录当前回合的策略和执行动作
                current_strategy = self.strategy_history[-1] if self.strategy_history else ""
                
                state = {
                    "waste_blocks": waste_blocks, 
                    "reward_blocks": reward_blocks,
                    "slime_count": slime_count,
                    "mushroom_count": mushroom_count,
                    "strategy": current_strategy,
                    "recommend_strategy": AgentState.recommend_strategy,
                }
                
                self.state_history.append((reward_blocks, waste_blocks))
                print(f"State extracted: {state}")
                result.update({"state": state})
            else:
                print("未找到匹配内容")
            
        result = {}

        ai_summary_subtask(result, chat_log)
        print(f"Subtask summary completed.")
        return result

    def summary_task(self, turn_seconds, events, max_retries=5):
        # every episode summary
        #1.reward blocks and waste blocks count
        #2.history actually strategy
        #3.history recommend strategy
        #4.current state
        reward = 0

        return reward


    def save_episode(self, results):
        U.dump_json(results, f"{self.save_dir}/episodes/episode{self.episode}/code.json")

    def load_episode(self, episode): 
        if not isinstance(episode, int):
            raise ValueError("episode must be an integer")
        
        file_name = f"{self.save_dir}/episodes/episode{episode}/code.json"
        json_contents = U.json_load(file_name)
        return json_contents
    
    # def replay_episode(self, episode):
    #     if not isinstance(episode, int):
    #         raise ValueError("episode must be an integer")

    #     episode_results = self.load_episode(episode)
    #     self.run_threads(env_step, args=episode_results)

    def recommend_strategy(self, agents, current_strategy, real_strategy, real_state):
        """Generate real-time strategy recommendation"""
        if not agents:
            return ""
        print(f"Generating strategy for agents...")
        for agent in agents:
            if not hasattr(agent, 'username'):
                continue
            #推荐逻辑
        
        # strategy = MushroomStrategy()

        # 加载值集（请替换为实际的CSV文件路径）
        csv_file_path = self.csv_file_path
        self.strategy.load_value_sets_from_csv(csv_file_path)

       
        # 计算最优策略
        print(f"real_state: {real_state} current_strategy: {current_strategy} real_strategy: {real_strategy} ")
        
        # 参数验证和默认值设置
        # 验证real_state（current_state参数）
        if not (isinstance(real_state, tuple) and len(real_state) == 2 and 
                all(isinstance(x, int) for x in real_state)):
            print(f"Warning: Invalid real_state {real_state}, using default (0, 0)")
            real_state = (0, 0)
        
        # 验证current_strategy（current_policy参数）
        valid_actions = ["hunt", "clean"]
        if not (isinstance(current_strategy, tuple) and len(current_strategy) == 2 and 
                all(action in valid_actions for action in current_strategy)):
            print(f"Warning: Invalid current_strategy {current_strategy}, using default ('hunt', 'clean')")
            current_strategy = ('hunt', 'clean')
        
        # 验证real_strategy（current_policy_player参数）
        if not (isinstance(real_strategy, tuple) and len(real_strategy) == 2 and 
                all(action in valid_actions for action in real_strategy)):
            print(f"Warning: Invalid real_strategy {real_strategy}, using default ('hunt', 'hunt')")
            real_strategy = ('hunt', 'hunt')
        
        # # 验证num_steps
        # if not (isinstance(num_steps, int) and num_steps > 0):
        #     print(f"Warning: Invalid num_steps {num_steps}, using default 5")
        #     num_steps = 5
        
        recommend_strategy = self.strategy.recommend_strategy(real_state, current_strategy, real_strategy, num_steps=5)

        # # 计算最优策略
        # print(f"real_state: {real_state} current_strategy: {current_strategy} real_strategy: {real_strategy} ")
        # recommend_strategy = self.strategy.recommend_strategy(real_state, current_strategy, real_strategy, num_steps=5)

            #
        print(f"Recommended strategy: {recommend_strategy}")   
        # recommend_strategy = f"""
        # [RECOMMENDED STRATEGY]:
        # agent1: {agent.username} recommend_strategy:mushroom{2}, waste_block:{1};
        # agent2: {agent.username} recommend_strategy:mushroom{3}, waste_block:{4};
        # """
        self.recommend_strategy_history.append(recommend_strategy)
        
        return recommend_strategy

    def run_episode(self, episode=None, reload=True, reset='soft'):
        # Real-time strategy monitoring
        
        def strategy_monitor(real_strategy_count):
            AgentState.real_strategy_count = real_strategy_count
            try:
                # Get current state from all agents
                agent_events = {}
                for agent in self.agents:
                    # Get real events from agent
                    events = getattr(agent, 'last_events', [])
                    agent_events[agent.username] = events
                
                # Get historical strategies and states
                AgentState.current_strategy = self.recommend_strategy_history[-1] if self.recommend_strategy_history else None
                #
                AgentState.real_strategy = self.strategy_history[-1] if self.strategy_history else None
                #
                AgentState.real_state = self.state_history[-1] if self.state_history else None

                 # 第一次边界监测
                if AgentState.current_strategy is None:
                    AgentState.current_strategy = ('hunt', 'hurt')
                if AgentState.real_strategy is None:
                    AgentState.real_strategy = ('hunt', 'hunt')
                if AgentState.real_state is None:
                    AgentState.real_state = (18, 11)
                
                # Generate context-aware strategy for all agents
               
                print(f"Generating recommended strategy based on current state and history...")
                AgentState.recommend_strategy = self.recommend_strategy(self.agents, AgentState.current_strategy, AgentState.real_strategy, AgentState.real_state)


                print(f"Strategy updated: {AgentState.recommend_strategy}")
                
            except Exception as e:
                print(f"Strategy monitor error for agents: {e}")
                import traceback
                traceback.print_exc()

        # get ai_message and parse
        def get_ai_message_parse(agent, result):
            if agent.action_agent_rollout_num_iter < 0:
                raise ValueError("Agent must be reset before stepping")
            ai_message = agent.action_agent.llm(agent.messages)
            # print(f"AI message received: {agent.messages}")
            agent.logger(f"\033[34m****Action Agent ai message****\n{ai_message.content}\033[0m")
            agent.conversations.append(
                (agent.messages[0].content, agent.messages[1].content, ai_message.content)
            )
            parsed_result = agent.action_agent.process_ai_message(message=ai_message)
            result.update({'parsed_result': parsed_result})

        # do env.step with improved error handling and timeout protection
        def env_step(agent, result, parsed_result):
            if not isinstance(parsed_result, dict):
                assert isinstance(parsed_result, str)
                print('parsed_result', parsed_result)
                agent.recorder.record([], agent.task) 
                agent.logger(f"\033[34m{parsed_result} Trying again!\033[0m")

            code = parsed_result["program_code"] + "\n" + parsed_result["exec_code"]
            events = agent.env.step(
                f"await saveRewards(bot, {U.json_dumps(self.reward_item_names)}, '{self.save_dir}/episodes/episode{self.episode}');"
                + code,
                programs=agent.skill_manager.programs,
            )
            agent.recorder.record(events, agent.task) # what is this for??
            self.update_chest_memory(events[-1][1]["nearbyChests"])
            result.update({'events': events})

        # update messages for next round
        def update_agent(agent, result, AgentState, parsed_result, events, success, critique, contract_critique, emeralds):
            new_skills = agent.skill_manager.retrieve_skills(
                query=agent.context
                + "\n\n"
                + agent.action_agent.summarize_chatlog(events)
            )
            system_message = agent.action_agent.render_system_message(skills=new_skills)
            human_message = agent.action_agent.render_human_message(
                events=events,
                code=parsed_result["program_code"],
                task=agent.task,
                contract=agent.contract,
                scenario=agent.scenario,
                context=agent.context,
                critique=critique,
                contract_critique=contract_critique,
                real_strategy_count=AgentState.real_strategy_count,
                current_strategy=AgentState.current_strategy,
                real_strategy=AgentState.real_strategy,
                real_state=AgentState.real_state,
                recommend_strategy=AgentState.recommend_strategy,
            )
            agent.last_events = copy.deepcopy(events)
            agent.messages = [system_message, human_message]
            assert len(agent.messages) == 2
            agent.action_agent_rollout_num_iter += 1
            # checkpointing
            print(f"check")
            print(AgentState.real_strategy_count, AgentState.current_strategy, AgentState.real_strategy, AgentState.real_state)

            done = (
                agent.action_agent_rollout_num_iter >= agent.action_agent_task_max_retries
                or success
            )
            info = {
                "task": agent.task,
                "success": success,
                "conversations": agent.conversations,
                "emeralds": emeralds
            }
            if success:
                assert (
                    "program_code" in parsed_result and "program_name" in parsed_result
                ), "program and program_name must be returned when success"
                info["program_code"] = parsed_result["program_code"]
                info["program_name"] = parsed_result["program_name"]
            
            agent.logger(
                f"\033[32m****Action Agent human message****\n{agent.messages[-1].content}\033[0m"
            )
            result.update({'messages': agent.messages, 'done': done, 'info': info})

        # replace chat events with those from the agent who lived longest and save both players observations
        # note: this is a hacky solution to a problem that should be fixed in the future
        def fix_chat_events(events):
            if not isinstance(events, dict):
        # 确保列表非空
                if isinstance(events, list) and len(events) > 0:
                    events = events[-1]
                else:
                    # 如果不是字典也不是有效的列表，返回空结构
                    return {agent.username: {'events': []} for agent in self.agents}
            # collect all chat events for each agent
            chat_events = {agent.username: [] for agent in self.agents}
            other_events = {agent.username: [] for agent in self.agents}
            for agent, other_agent in [self.agents, self.agents[::-1]]: # wont work if num_agents != 2
                for (event_type, event) in events[agent.username]['events']:
                    if event_type == 'onChat':
                        chat_events[agent.username].append((event_type, event))
                    # record both agents observations for reading inventory etc
                    elif event_type == 'observe':
                        other_events[other_agent.username].insert(0, ('otherObserve', event))
                        other_events[agent.username].append((event_type, event))
                    else:
                        other_events[agent.username].append((event_type, event))
            # copy in longest thread of chats
            longest_thread = max(chat_events.values(), key=len)
            new_events = {agent.username: {'events': longest_thread + other_events[agent.username]} for agent in self.agents}

            # copy one of the agents events for the judge
            new_events[self.judge_username] = new_events[self.agents[0].username]
            # print('fix_chat_events, events:', events)
            # print('fix_chat_events, new_events:', new_events)
            return new_events
        def fix_event(events):
            
            events = events[self.agents[0].username]['events']
            chat_messages = []
            for i, (event_type, event) in enumerate(events):
                if event_type == "onChat":
                    chat_messages.append(event["onChat"])

            chat_log = "\n".join(chat_messages)
            print("chat_log:", chat_log)
            return chat_log

        
            
        def fix_chat_state_events(events):
            chat_events = {agent.username: "" for agent in self.agents}
            # print("events", events)
            for agent in self.agents:
                    for (event_type, event) in events[agent.username]['events']:
                        
                        if event_type == 'onChat' :
                            event1 = event["onChat"]
                            chat_events[agent.username] += event1
            #print('fix_chat_events, events:', events)
            # print('fix_chat_events1, chat_events:', chat_events)
            #print('state_events:', state_events)
            


            pattern_hunt_Gizmo = r"<Gizmo> Harvested_mushroom"
            pattern_hunt_Glitch = r"<Glitch> Harvested_mushroom"
            pattern_clean_Gizmo = r"<Gizmo> Cleaned_slime"
            pattern_clean_Glitch = r"<Glitch> Cleaned_slime"
            # territory_pd.json: Defect_poison maps to 'hunt' (defect strategy)
            pattern_defect_Gizmo = r"<Gizmo> Defected_poison"
            pattern_defect_Glitch = r"<Glitch> Defected_poison"
           
            pattern_timeout_Gizmo = r"<Gizmo> Gizmo took (\d+)(?=ms)"
            pattern_timeout_Glitch = r'<Glitch> Glitch took (\d+)(?=ms)'
            real_strategy_agent1 = ""
            real_strategy_agent2 = ""
            timeout_Gizmo = 0
            timeout_Glitch = 0

            matches_hunt_Gizmo = re.findall(pattern_hunt_Gizmo, chat_events[self.agents[0].username])
            matches_hunt_Glitch = re.findall(pattern_hunt_Glitch, chat_events[self.agents[1].username])
            matches_clean_Gizmo = re.findall(pattern_clean_Gizmo, chat_events[self.agents[0].username])
            matches_clean_Glitch = re.findall(pattern_clean_Glitch, chat_events[self.agents[1].username])
            # territory_pd.json: Defected_poison → defect strategy (mapped to 'hunt')
            matches_defect_Gizmo = re.findall(pattern_defect_Gizmo, chat_events[self.agents[0].username])
            matches_defect_Glitch = re.findall(pattern_defect_Glitch, chat_events[self.agents[1].username])
            if matches_hunt_Gizmo:
                real_strategy_agent1 = 'hunt'
            if matches_clean_Gizmo:
                real_strategy_agent1 = 'clean'
            if matches_defect_Gizmo:
                real_strategy_agent1 = 'hunt'
            if matches_hunt_Glitch:
                real_strategy_agent2 = 'hunt'
            if matches_clean_Glitch:
                real_strategy_agent2 = 'clean'
            if matches_defect_Glitch:
                real_strategy_agent2 = 'hunt'
            matches_time_Gizmo = re.findall(pattern_timeout_Gizmo, chat_events[self.agents[0].username])
            matches_time_Glitch = re.findall(pattern_timeout_Glitch, chat_events[self.agents[1].username])
            if matches_time_Gizmo:
                for time in matches_time_Gizmo:
                    timeout_Gizmo += int(time)

            if matches_time_Glitch:
                for time in matches_time_Glitch:
                    timeout_Glitch += int(time)
            print ("matches_hunt_Gizmo", matches_hunt_Gizmo)
            print ("matches_clean_Gizmo", matches_clean_Gizmo)
            print ("matches_hunt_Glitch", matches_hunt_Glitch)
            print ("matches_clean_Glitch", matches_clean_Glitch)
            print ("timeout_Gizmo", timeout_Gizmo)
            print ("timeout_Glitch", timeout_Glitch)
            # for agent in self.agents:
                # if 'events' in events[agent.username]:
                #     for (event_type, event) in events[agent.username]['events']:
                        
                #         if event_type == 'onChat' :
                #             if agent.username == self.agents[0].username:
                #                 print ("event11", event1)
                #             event1 = event["onChat"]
                #             print("event1", event1)
                #             # print("agent.username", agent.username)
                #             # chat_events[agent.username].append((event_type, event1))

                            
                #             matches_hunt_Gizmo = re.findall(pattern_hunt_Gizmo, event1)
                #             matches_clean_Gizmo = re.findall(pattern_clean_Gizmo, event1)
                #             matches_hunt_Glitch = re.findall(pattern_hunt_Glitch, event1)
                #             matches_clean_Glitch = re.findall(pattern_clean_Glitch, event1)
                            
                            
                #             matches_time_Gizmo = re.findall(pattern_timeout_Gizmo, event1)
                            
                #             matches_timeout_Gizmo = int(matches_time_Gizmo[-1]) if matches_time_Gizmo else 0
                #             if (matches_timeout_Gizmo > 0):
                #                 timeout_Gizmo += matches_timeout_Gizmo
                #                 print("matches_timeout_Gizmo:", matches_timeout_Gizmo)
                #                 print("timeout_Gizmo:", timeout_Gizmo)
                        
                #             matches_time_Glitch = re.findall(pattern_timeout_Glitch, event1)
                #             matches_timeout_Glitch = int(matches_time_Glitch[-1]) if matches_time_Glitch else 0
                #             if (matches_timeout_Glitch > 0):
                #                 timeout_Glitch += matches_timeout_Glitch
                #                 print("matches_timeout_Glitch:", matches_timeout_Glitch)
                #                 print("timeout_Glitch:", timeout_Glitch)

                # if matches_hunt_Gizmo:
                #     real_strategy_agent1 = 'hunt'
                # if matches_clean_Gizmo:
                #     real_strategy_agent1 = 'clean'
                # if matches_hunt_Glitch:
                #     real_strategy_agent2 = 'hunt'
                # if matches_clean_Glitch:
                #     real_strategy_agent2 = 'clean'
                            


            timeout_Gizmo = timeout_Gizmo / 1000 
            timeout_Glitch = timeout_Glitch / 1000 
            real_timeout = (timeout_Gizmo, timeout_Glitch)
            print("real_timeout:", real_timeout)
            self.timeout_history.append(real_timeout)
            real_strategy = (real_strategy_agent1, real_strategy_agent2)
            
            print("real_strategy:", real_strategy)

            # print('fix_chat_events, chat_events:', chat_events)
            return chat_events, real_strategy

        # reset for both agents and load scenario
        if reload:
            self.load_scenario(reset=reset)
            # time.sleep(3) # wait for voyagers and scenario to load
        
        # if a specific episode is provided, look for contract and play it
        # ideally this should be moved to a different function (except env_step should be moved too)
        if episode is not None:
            if not isinstance(episode, int):
                raise ValueError("episode must be an integer")
            
            episode_results = self.load_episode(episode)
            # self.run_threads(env_step, args=episode_results)
            self.reset_agents()
            return
        
        events = {}
        real_strategy_count = 0


        while real_strategy_count < self.total_strategy_count:
            print(f'=== Starting Game Round {real_strategy_count + 1}/{self.total_strategy_count} ===')
            
            # Initialize round statistics
            # round_mushroom_total = 0
            # round_slime_total = 0
            
            # Each round consists of multiple turns
            total_time = 0
            turn_count = 0
            max_turns_per_round = 10  # 设置每轮的最大回合数
            slime_count = 0
            mushroom_count = 0
            self.pause_agents()

            while total_time <= self.total_time_limit:

                turn_count += 1
                print(f'--- Turn {turn_count} of Round {real_strategy_count + 1} ---')
                    
                # Step 1: Pause game and get strategy recommendation
                
                print('Getting strategy recommendation...')
                strategy_monitor(turn_count)
                
                #状态更新需要在check_task_success之后，这样才能拿到最新的状态信息
                if turn_count > 1:
                    critic_response = self.check_task_success(events)
                    results = self.run_threads(update_agent, args={
                        agent.username: {
                            **parsed_results[agent.username],
                            **events[agent.username], 
                            **critic_response[agent.username],
                            'contract_critique': critic_response[self.judge.username]['critique'],
                            'emeralds': critic_response[self.judge.username]['emeralds'],
                            'AgentState': AgentState,
                        } for agent in self.agents}
                    )

                # Step 2: LLM decides on turn strategy based on recommendation
                print(f'LLM deciding on turn strategy, real_strategy_count: {real_strategy_count}, turn_count: {turn_count}')
                parsed_results = self.run_threads(get_ai_message_parse)
                
                self.save_episode(parsed_results)
                
                # Step 3: Resume game and execute strategy with thread pool
                self.unpause_agents()
                print('Executing env step')
                # Step 4: Update time
                results = self.run_threads(env_step, args=parsed_results)

                
                # Step 4: Pause game and summarize turn
                self.pause_agents()
                print('Summarizing turn...')

                events = results  # results contains events from env_step
                
                
                new_events, real_strategy = fix_chat_state_events(events)
                self.strategy_history.append(real_strategy)
                
                print(f'summarized Turn {turn_count} of Round {real_strategy_count + 1} ---')
                events = fix_chat_events(events)
                self.total_event = events
                chat_log = fix_event(events)
                # Summarize subtask with environmental information
                self.summary_subtask(chat_log)
                real_timeout = self.timeout_history[-1] if self.timeout_history else (0, 0)
                max_timeout = max(real_timeout)    
                total_time += max_timeout if max_timeout is not None else 0
                print(f"Updated total_time: {total_time} seconds after adding max timeout: {max_timeout} seconds")
                print(f"total_time/turn_count: {total_time}/{turn_count}")
                
                # Step 5: Check for task success and update agents
                print('check_task_success for turn')
                
                

                
                
            # Step 6: Round summary
            print(f'=== Round {real_strategy_count + 1} Summary ===')
            print('========================')
            critic_response = self.check_task_success(self.total_event)
            self.unpause_agents()
            real_strategy_count += 1 
            print(f'Strategy count completed: {real_strategy_count}')
            results = self.run_threads(update_agent, args={
                    agent.username: {
                        **parsed_results[agent.username],
                        **events[agent.username], 
                        **critic_response[agent.username],
                        'contract_critique': critic_response[self.judge.username]['critique'],
                        'emeralds': critic_response[self.judge.username]['emeralds'],
                        'AgentState': AgentState,
                    } for agent in self.agents}
                )

        return results

    def negotiate_contract(self, max_turns=12):
        """
        Generates a contract for the agents to follow and sets self.contract to the contract.
        """
        print('Negotiating contract...')
        
        if self.scenario_description is None:
            raise ValueError("Scenario must be loaded before negotiating contract")
        
        agent1 = self.agents[0]
        agent2 = self.agents[1]

        negotiator1 = Negotiator(
            name=agent1.username,
            task=agent1.task,
            other_name=agent2.username,
            other_task=agent2.task,
            scenario=self.scenario_description,
            model=self.negotiator_model_name,
            temperature=self.negotiator_temperature,
            #model_api_base=self.negotiator_model_api_base,
        )
        negotiator2 = Negotiator(
            name=agent2.username,
            task=agent2.task,
            other_name=agent1.username,
            other_task=agent1.task,
            scenario=self.scenario_description,
            model=self.negotiator_model_name,
            temperature=self.negotiator_temperature,
            #model_api_base=self.negotiator_e,
        )

        # hold a negotiation between players, where negotiator1 starts first
        print(f"Negotiating contract between {agent1.username} and {agent2.username}...")


        negotiation = Negotiation(negotiator1, negotiator2, max_turns=max_turns, save_dir=self.save_dir)
        print(f"Negotiation started with max turns {max_turns}...")
        negotiation.simulate()
        self.contract = negotiation.get_contract()

    def run(self):
        max_startup_attempts = 3
        for startup_attempt in range(max_startup_attempts):
            try:
                if self.load_from_save:
                    input("Warning: loaded from saved directory. Continuing may overwrite saved files. Press enter to continue...")

                self.load_scenario(reset='hard')
                break  # Successfully started, break out of retry loop
            except Exception as e:
                print(f"Startup attempt {startup_attempt + 1}/{max_startup_attempts} failed: {e}")
                if startup_attempt == max_startup_attempts - 1:
                    print("All startup attempts failed, shutting down...")
                    self.close()
                    return
                print("Restarting mineflayer servers and retrying...")
                # Clean up and restart servers
                for agent in self.agents + [self.judge]:
                    if hasattr(agent, 'env') and hasattr(agent.env, 'mineflayer'):
                        agent.env.mineflayer.stop()
                time.sleep(5)
        else:
            print("Failed to start after multiple attempts")
            self.close()
            return
        
        # load the contract
        if self.contract_mode == "auto":
            if self.contract is not None:
                print("Warning: contract provided but contract_mode is 'auto'. Contract will be ignored.")
            print('Negotiating contract...')
            self.negotiate_contract()

        # save contract to file
        with open(f"{self.save_dir}/contract.txt", 'w') as contract_file:
            contract_file.write(self.contract)

        # set agent tasks and contract
        self.run_threads(lambda agent, _, args: agent.reset(task=agent.task, **args), args={'args': {
            'contract': self.contract,
            'scenario': self.scenario_description,
            'context': "",
            'reset_env': False,}}, shared_args=True)

        replay = False
        done = False
        while not done or replay:
            if replay:
                print('Repeating episode...')
                self.run_episode(episode=self.episode, reload=True, reset='soft')
            else:
                U.f_mkdir(f"{self.save_dir}/episodes/episode{self.episode}")
                print(f'Starting episode {self.episode}...')
                # dont load episode if its already loaded
                reload = False if self.episode == 0 else True
                results = self.run_episode(reload=reload, reset='soft')

                # If all tasks were successful, stop
                # agent_successes = [result['info']['success'] for result in results.values()]
                # success = all(agent_successes)

                # # stop episode from ending
                # success = False
                
                # Print successes
                for agent in self.agents:
                    print(f"{agent.username} {{emeralds: {results[agent.username]['info']['emeralds']}}}")

                # save emerald values
                U.json_dump({agent.username: results[agent.username]['info']['emeralds'] for agent in self.agents}, f"{self.save_dir}/episodes/episode{self.episode}/emeralds.json")

                # if success:
                #     user_response = input("Episode success. Press enter to close or 'r' to repeat...")
                #     if user_response == 'r': 
                #         replay = True
                #     else: 
                #         break
            
            # if not continuous mode wait to continue
            if self.continuous:
                self.episode += 1
                if self.episode == self.num_episodes:
                    done = True

            else:
                user_response = input("Press enter to continue or 'r' to repeat...")
                if user_response == 'r':
                    replay = True
                else:
                    replay = False
                    self.episode += 1 # only increment if not replaying

        print('Quitting...') 
    
    def close(self):
        print('Closing...')
        server = self.judge.env.server
        res = requests.post(f"{server}/stop")
        for agent in self.agents + [self.judge]:
            agent.env.mineflayer.stop()
        
        # Wait for all threads to terminate
        for agent in self.agents + [self.judge]:
            if hasattr(agent, '_thread') and agent._thread.is_alive():
                agent._thread.join(timeout=1.0)
