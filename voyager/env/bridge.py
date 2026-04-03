import os.path
import time
import warnings
from typing import SupportsFloat, Any, Tuple, Dict

import requests
import json

import gymnasium as gym
from gymnasium.core import ObsType

import voyager.utils as U

from .minecraft_launcher import MinecraftInstance
from .process_monitor import SubprocessMonitor


class VoyagerEnv(gym.Env):
    def __init__(
        self,
        mc_port=None,
        username="bot",
        azure_login=None,
        server_host="http://127.0.0.1",
        server_port=3000,
        request_timeout=600,
        log_path="./logs",
    ):
        if not mc_port and not azure_login:
            raise ValueError("Either mc_port or azure_login must be specified")
        if mc_port and azure_login:
            warnings.warn(
                "Both mc_port and mc_login are specified, mc_port will be ignored"
            )
        self.mc_port = mc_port
        self.username = username
        self.azure_login = azure_login
        self.server = f"{server_host}:{server_port}"
        self.server_port = server_port
        self.request_timeout = request_timeout
        self.log_path = log_path
        self.mineflayer = self.get_mineflayer_process(server_port)
        if azure_login:
            self.mc_instance = self.get_mc_instance()
        else:
            self.mc_instance = None
        self.has_reset = False
        self.reset_options = None
        self.connected = False
        self.server_paused = False

    def get_mineflayer_process(self, server_port):
        U.f_mkdir(self.log_path, "mineflayer")
        file_path = os.path.abspath(os.path.dirname(__file__))
        return SubprocessMonitor(
            commands=[
                "node",
                U.f_join(file_path, "mineflayer/index.js"),
                str(server_port),
            ],
            name="mineflayer",
            ready_match=r"Server started on port (\d+)",
            log_path=U.f_join(self.log_path, "mineflayer"),
        )
    def reset_connection(self):
        """
        Reset the connection to the Minecraft server.
        """
        print(f"Resetting connection for {self.username}...")
        
        try:
            # First try to stop gracefully
            if self.connected:
                requests.post(f"{self.server}/stop", timeout=5)
                self.connected = False
        except Exception as e:
            print(f"Error stopping connection: {e}")
        
        # Restart mineflayer process
        self.mineflayer.stop()
        time.sleep(2)  # Give it time to stop
        
        # Start mineflayer process again
        self.mineflayer.run()
        time.sleep(3)  # Give it time to start
        
        # Reset connection status
        self.has_reset = False
        self.connected = False
        
        # If reset options exist, try to reconnect
        if self.reset_options:
            try:
                # Try to reconnect with existing reset options
                returned_data = self.check_process()
                if returned_data:
                    self.has_reset = True
                    self.connected = True
                    print(f"Connection reset successful for {self.username}")
                    return True
            except Exception as e:
                print(f"Error reconnecting: {e}")
        
        print(f"Connection reset failed for {self.username}")
        return False
    def get_mc_instance(self):
        print("Creating Minecraft server")
        U.f_mkdir(self.log_path, "minecraft")
        return MinecraftInstance(
            **self.azure_login,
            mineflayer=self.mineflayer,
            log_path=U.f_join(self.log_path, "minecraft"),
        )

    def check_process(self):
        if self.mc_instance and not self.mc_instance.is_running:
            # if self.mc_instance:
            #     self.mc_instance.check_process()
            #     if not self.mc_instance.is_running:
            print("Starting Minecraft server")
            self.mc_instance.run()
            self.mc_port = self.mc_instance.port
            self.reset_options["port"] = self.mc_instance.port
            print(f"Server started on port {self.reset_options['port']}")
        retry = 0
        while not self.mineflayer.is_running and retry <= 3:
            retry += 1
            print("Mineflayer process has exited, restarting")
            self.mineflayer.run()
            if not self.mineflayer.is_running:
                continue

        max_retries = 8
        base_wait_time = 3
        for retry in range(max_retries):
            # Wait longer between retries for subsequent attempts
            # if retry > 0:
            #     wait_time = base_wait_time * (retry + 1)
            #     print(f"Waiting {wait_time} seconds before retry {retry + 1}/{max_retries}...")
            #     url, host, port = str(self.server).split(':')
            #     new_port = int(port) + retry -1
            #     self.server = f"{url}:{host}:{new_port}"
            #     print(f"{self.server}")
                
            #     time.sleep(wait_time)
            
            try:
                # Check if mineflayer process is running
                if not self.mineflayer.is_running:
                    print("Mineflayer process not running, restarting...")
                    self.mineflayer.run()
                    # Give it some time to start
                    time.sleep(2)
                
                res = requests.post(
                    f"{self.server}/start",
                    json=self.reset_options,
                    timeout=10,
                )
                
                if res.status_code != 200:
                    print(f"Minecraft server reply with code {res.status_code}, retrying...")
                    continue
                
                print(f"Server {self.server} started successfully")
                return res.json()
                
            except requests.exceptions.ConnectionError as e:
                print(f'Connection error to {self.server}, retry {retry + 1}/{max_retries}: {str(e)}')
                # Restart mineflayer on connection errors
                self.mineflayer.stop()
                time.sleep(1)
                self.mineflayer.run()
                time.sleep(2)
                
            except requests.exceptions.Timeout as e:
                print(f'Timeout connecting to {self.server}, retry {retry + 1}/{max_retries}: {str(e)}')
                
            except Exception as e:
                print(f'bot start failed, retry {retry + 1}/{max_retries}: {str(e)}')
        
        print(f"Warning: Failed to start bot after {max_retries} retries, returning empty response")
        return "{}"  # Return empty JSON object

    def step(
        self,
        code: str,
        programs: str = "",
    ) -> Tuple[ObsType, SupportsFloat, bool, bool, Dict[str, Any]]:
        if not self.has_reset:
            raise RuntimeError("Environment has not been reset yet")
        self.check_process()
        # self.unpause()
        data = {
            "code": code,
            "programs": programs,
        }
        
        res = requests.post(
            f"{self.server}/step", json=data, timeout=self.request_timeout
        )
        #需要看下request请求的逻辑
        if res.status_code != 200:
            raise RuntimeError(
                f"Minecraft server reply with code {res.status_code}"
            )

        returned_data = res.json()
        # self.pause()
        return json.loads(returned_data)

    def render(self):
        raise NotImplementedError("render is not implemented")

    def reset(
        self,
        *,
        seed=None,
        options=None,
    ) -> Tuple[ObsType, Dict[str, Any]]:
        if options is None:
            options = {}

        if options.get("inventory", {}) and options.get("mode", "hard") != "hard":
            raise RuntimeError("inventory can only be set when options is hard")

        self.reset_options = {
            "port": self.mc_port,
            "username": self.username,
            "reset": options.get("mode", "hard"),
            "inventory": options.get("inventory", {}),
            "equipment": options.get("equipment", []),
            "spread": options.get("spread", False),
            "waitTicks": options.get("wait_ticks", 5),
            "position": options.get("position", None),
        }

        # self.unpause()
        self.mineflayer.stop()
        time.sleep(1)  # wait for mineflayer to exit

        returned_data = self.check_process()
        # print(f"reset returned data: {returned_data}")
        if returned_data is None:
            returned_data = "{}"  # Return empty JSON object if None
        self.has_reset = True
        self.connected = True
        # All the reset in step will be soft
        self.reset_options["reset"] = "soft"
        # self.pause()
        return json.loads(returned_data)

    def close(self):
        print('close')
        # self.unpause()
        if self.connected:
            res = requests.post(f"{self.server}/stop")
            if res.status_code == 200:
                self.connected = False
        if self.mc_instance:
            self.mc_instance.stop()
        self.mineflayer.stop()
        return not self.connected

    def pause(self):
        if self.mineflayer.is_running and not self.server_paused:
            res = requests.post(f"{self.server}/pause")
            print(res.json())
            if res.status_code == 200:
                self.server_paused = True
        return self.server_paused

    def unpause(self):
        if self.mineflayer.is_running and self.server_paused:
            res = requests.post(f"{self.server}/pause")
            if res.status_code == 200:
                self.server_paused = False
            else:
                print(res.json())
        return self.server_paused
