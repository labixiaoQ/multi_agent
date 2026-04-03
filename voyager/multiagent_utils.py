import re

class Utils:
    """Utility functions for the multi-agent system"""
    
    def __init__(self):
        pass
    
    def fix_chat_events(self, agents, events):
        """
        Replace chat events with those from the agent who lived longest and save both players observations
        note: this is a hacky solution to a problem that should be fixed in the future
        """
        # collect all chat events for each agent
        chat_events = {agent.username: [] for agent in agents}
        other_events = {agent.username: [] for agent in agents}
        
        # Iterate through agent pairs
        for agent, other_agent in [agents, agents[::-1]]: # wont work if num_agents != 2
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
        new_events = {agent.username: {'events': longest_thread + other_events[agent.username]} for agent in agents}

        # copy one of the agents events for the judge
        judge_username = 'Judy'  # This should be passed in as a parameter
        new_events[judge_username] = new_events[agents[0].username]
        
        return new_events
    
    def fix_chat_state_events(self, events):
        """Fix chat state events and extract state information"""
        chat_events = {}
        state_events = []
        
        # Iterate through agent pairs
        for agent_username, agent_events in events.items():
            chat_events[agent_username] = []
            if 'events' in agent_events:
                for (event_type, event) in agent_events['events']:
                    if event_type == 'onChat':
                        # Extract numbers from chat messages
                        numbers = re.findall(r'\d+', event["onChat"])
                        numbers_as_int = [int(num) for num in numbers]
                        state_events = numbers_as_int
                        #print("state_events", state_events)
                        
                        event1 = event["onChat"]
                        # Check if judge is mentioned in the chat
                        if 'Judy' in event1:  # This should be passed in as a parameter
                            chat_events[agent_username].append((event_type, event1))
        
        return chat_events
    
    def update_chest_memory(self, chests, chest_memory, agents, judge):
        """Update global chest memory and synchronize it across all agents"""
        for position, chest in chests.items():
            if position in chest_memory:
                if isinstance(chest, dict):
                    chest_memory[position] = chest
                if chest == "Invalid":
                    print(
                        f"\033[32mRemoving chest {position}: {chest}\033[0m"
                    )
                    chest_memory.pop(position)
            else:
                if chest != "Invalid":
                    print(f"\033[32mSaving chest {position}: {chest}\033[0m")
                    chest_memory[position] = chest

        # Update agent chest memories
        for agent in agents + [judge]:
            agent.action_agent.chest_memory = chest_memory
