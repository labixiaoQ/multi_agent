"""
统一实验入口：信息集梯度 × LLM 模型 × 场景类型

用法示例：
  # L2 信息等级，gpt-3.5-turbo，cleanup 场景，5 局，无合约
  python run_experiment.py --model gpt-3.5-turbo --info-level 2 --scenario cleanup --contract none --num-games 5

  # 相同场景/信息等级，换模型对比
  python run_experiment.py --scenario cleanup --info-level 2 --model gpt-4o --num-games 5
  python run_experiment.py --scenario cleanup --info-level 2 --model deepseek-chat --num-games 5

  # 自动谈判合约
  python run_experiment.py --model gpt-3.5-turbo --info-level 2 --scenario cleanup --contract auto --num-games 5

信息等级梯度：
  L0 Blind:   show_chat_log=False, show_execution_error=False, show_strategy=False
  L1 Social:  show_chat_log=True,  show_execution_error=False, show_strategy=False
  L2 Guided:  show_chat_log=True,  show_execution_error=False, show_strategy=True
  L3 Full:    show_chat_log=True,  show_execution_error=True,  show_strategy=True
"""

import argparse
import json
import re
import time
from datetime import datetime

import voyager.utils as U
from voyager import MultiAgentVoyager
from api_keys import openai_api_key

# ─── 信息等级映射表 ────────────────────────────────────────────────
INFO_LEVEL_FLAGS = {
    0: dict(show_chat_log=False, show_execution_error=False, show_strategy=False),
    1: dict(show_chat_log=True,  show_execution_error=False, show_strategy=False),
    2: dict(show_chat_log=True,  show_execution_error=False, show_strategy=True),
    3: dict(show_chat_log=True,  show_execution_error=True,  show_strategy=True),
}

INFO_LEVEL_NAMES = {
    0: "Blind",
    1: "Social",
    2: "Guided",
    3: "Full",
}


def sanitize_model_name(model: str) -> str:
    """将模型名转换为合法的目录名（替换 / : 空格）"""
    return re.sub(r"[/:\s]", "_", model)


def write_metadata(game_dir: str, **kwargs):
    """在游戏目录中写入 metadata.json"""
    metadata_path = f"{game_dir}/metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(kwargs, f, ensure_ascii=False, indent=2)


def negotiate_contract(multi_options: dict, save_base: str) -> str:
    """自动谈判合约，返回合约文本（失败则抛异常）"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    neg_dir = f"{save_base}/negotiation_{timestamp}"
    U.f_mkdir(neg_dir)

    contract_env = MultiAgentVoyager(
        **multi_options,
        contract_mode="auto",
        save_dir=neg_dir,
    )
    contract_env.load_scenario(reset="hard")

    for attempt in range(3):
        try:
            contract_env.negotiate_contract()
            break
        except Exception as e:
            print(f"[run_experiment] 谈判第 {attempt + 1}/3 次失败: {e}")
            time.sleep(5)

    if contract_env.contract is None:
        contract_env.close()
        raise RuntimeError("合约谈判失败，已重试 3 次")

    contract_text = contract_env.contract
    contract_env.close()
    print(f"[run_experiment] 谈判成功，合约：\n{contract_text}\n")
    return contract_text


def main():
    parser = argparse.ArgumentParser(
        description="Voyager 多智能体实验自动化运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-3.5-turbo",
        help="LLM 模型名，同时用于 action_agent / critic_agent / negotiator（默认 gpt-3.5-turbo）",
    )
    parser.add_argument(
        "--info-level",
        type=int,
        choices=[0, 1, 2, 3],
        default=2,
        help="信息等级 0=Blind 1=Social 2=Guided 3=Full（默认 2）",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="cleanup",
        help="场景名（不含 .json），如 cleanup / harvest / territory_pd / volunteer_cave（默认 cleanup）",
    )
    parser.add_argument(
        "--contract",
        type=str,
        default="none",
        help='"none" | "auto" | "<合同文本>"（默认 none）',
    )
    parser.add_argument(
        "--num-games",
        type=int,
        default=5,
        help="游戏局数（默认 5）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=49172,
        help="Minecraft 服务器端口（默认 49172）",
    )
    args = parser.parse_args()

    model = args.model
    info_level = args.info_level
    scenario = args.scenario
    contract_arg = args.contract
    num_games = args.num_games
    mc_port = args.port

    flags = INFO_LEVEL_FLAGS[info_level]
    level_name = INFO_LEVEL_NAMES[info_level]
    model_safe = sanitize_model_name(model)

    # 确定合约类型标签（用于目录命名）
    if contract_arg == "none":
        contract_type = "none"
    elif contract_arg == "auto":
        contract_type = "auto"
    else:
        contract_type = "manual"

    save_base = f"saves/{scenario}/{model_safe}/info_L{info_level}/contract_{contract_type}"
    U.f_mkdir(save_base)

    print(f"\n{'='*60}")
    print(f"[run_experiment] 实验配置")
    print(f"  模型:     {model}")
    print(f"  信息等级: L{info_level} - {level_name}")
    print(f"    show_chat_log        = {flags['show_chat_log']}")
    print(f"    show_execution_error = {flags['show_execution_error']}")
    print(f"    show_strategy        = {flags['show_strategy']}")
    print(f"  场景:     {scenario}.json")
    print(f"  合约模式: {contract_type}")
    print(f"  局数:     {num_games}")
    print(f"  保存目录: {save_base}/")
    print(f"{'='*60}\n")

    # ─── 构建 options dict ──────────────────────────────────────────
    options = {
        "azure_login": None,
        "mc_port": mc_port,
        "openai_api_key": openai_api_key,
        "resume": False,
        "env_wait_ticks": 80,
        "env_request_timeout": 600,
        "action_agent_task_max_retries": 50,
        "action_agent_temperature": 0.3,
        "action_agent_model_name": model,
        "action_agent_show_chat_log": flags["show_chat_log"],
        "action_agent_show_execution_error": flags["show_execution_error"],
        "critic_agent_model_name": model,
    }

    # MultiAgentVoyager 共用参数
    multi_options = {
        "scenario_file": f"{scenario}.json",
        "continuous": True,
        "episode_timeout": 200,
        "num_episodes": 1,
        "negotiator_model_name": model,
        "negotiator_temperature": 0.7,
        "action_agent_show_strategy": flags["show_strategy"],
        "options": options,
    }

    # ─── 处理合约 ──────────────────────────────────────────────────
    if contract_arg == "auto":
        contract_text = negotiate_contract(multi_options, save_base)
        contract_mode_for_games = "manual"
    elif contract_arg == "none":
        contract_text = "None"
        contract_mode_for_games = "manual"
    else:
        contract_text = contract_arg
        contract_mode_for_games = "manual"

    # ─── 游戏主循环 ────────────────────────────────────────────────
    for game_i in range(num_games):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        game_dir = f"{save_base}/game_{timestamp}"
        # 注意：不在此处预先创建 game_dir，让 MultiAgentVoyager.__init__ 自行创建，
        # 否则非空目录会被误判为已有存档而触发 load_from_save 逻辑。

        print(f"[run_experiment] 开始第 {game_i + 1}/{num_games} 局 → {game_dir}")

        multi_agent = MultiAgentVoyager(
            **multi_options,
            contract_mode=contract_mode_for_games,
            contract=contract_text,
            save_dir=game_dir,
        )

        # MultiAgentVoyager 创建目录后再写入元数据
        write_metadata(
            game_dir,
            run_timestamp=datetime.now().isoformat(),
            scenario=scenario,
            model=model,
            info_level=info_level,
            info_level_name=level_name,
            info_flags=flags,
            contract_arg=contract_arg,
            contract_type=contract_type,
            contract_text=contract_text if contract_arg != "auto" else None,
            num_games=num_games,
            game_index=game_i,
            mc_port=mc_port,
            save_dir=game_dir,
        )

        multi_agent.run()
        multi_agent.close()

        print(f"[run_experiment] 第 {game_i + 1}/{num_games} 局完成\n")

    print(f"\n[run_experiment] 全部 {num_games} 局完成。结果保存在: {save_base}/")


if __name__ == "__main__":
    main()
