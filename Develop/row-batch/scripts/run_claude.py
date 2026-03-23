#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import subprocess
from datetime import datetime

# 设置 Git Bash 路径
#os.environ['CLAUDE_CODE_GIT_BASH_PATH'] = r'D:\2022tool\Git\bin\bash.exe'
MAX_TIME_OUT=1200

def detect_environment():
    """
    检测当前运行环境（claude 或 openclaw）

    Returns:
        str: 'claude' 或 'openclaw'
    """
    # 获取脚本所在目录的绝对路径
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 向上遍历目录树，查找路径以 .claude 或 .openclaw 结尾的目录
    current_dir = script_dir
    while current_dir != os.path.dirname(current_dir):  # 未到达根目录
        # 获取当前目录名
        dir_name = os.path.basename(current_dir)

        # 检查当前目录名是否是 .claude 或 .openclaw
        if dir_name == '.claude':
            return 'claude'
        if dir_name == '.openclaw':
            return 'openclaw'

        # 继续向上查找
        current_dir = os.path.dirname(current_dir)

    # 如果都找不到，默认返回 claude
    return 'claude'


def get_time_suffix():
    """生成带时间戳的输出文件名"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return timestamp

def check_file_size(filepath, max_size_mb=100):
    """检查文件大小是否超过限制"""
    if os.path.exists(filepath):
        size_bytes = os.path.getsize(filepath)
        size_mb = size_bytes / (1024 * 1024)
        return size_mb >= max_size_mb
    return False

def run_claude(skill_name, json_data, worker_id=None, output_dir=None, agent_name=None):
    """
    调用Claude CLI命令或OpenClaw命令，执行指定技能（不包括回库技能）

    Args:
        skill_name (str): 技能名称
        json_data (str or dict): JSON格式的输入数据（行数据）
        worker_id (str): 工作进程ID（可选）
        output_dir (str): 输出目录路径（可选），用于存放日志文件
        agent_name (str): OpenClaw环境下的agent名称（可选），格式为 skill_name小写+_worker1

    Returns:
        int: 命令的返回码
    """
    # 检测当前环境
    env_name = detect_environment()

    # 构建 log 文件路径
    if output_dir:
        # 确保 output_dir 存在
        os.makedirs(output_dir, exist_ok=True)
        if worker_id:
            log_filename = os.path.join(output_dir, f"{env_name}_log_worker_{worker_id}.txt")
        else:
            log_filename = os.path.join(output_dir, f"{env_name}_log.txt")
    else:
        # 兼容旧版本，输出到当前目录
        if worker_id:
            log_filename = f"{env_name}_log_worker_{worker_id}.txt"
        else:
            log_filename = f"{env_name}_log.txt"

    # 确保 json_data 是字符串格式
    if isinstance(json_data, dict):
        json_data = json.dumps(json_data, ensure_ascii=False)
    elif not isinstance(json_data, str):
        json_data = str(json_data)

    # 构建提示词
    prompt = f"调用技能{skill_name}，输入数据为{json_data}。"

    # 根据环境构建不同的命令
    if env_name == 'openclaw':
        # OpenClaw 环境：使用 openclaw agent 命令
        # 如果未传入 agent_name，则使用默认格式：skill_name小写 + "_worker1"
        if agent_name is None:
            agent_name = f"{skill_name.lower()}_worker1"
        command = [
            "openclaw",
            "agent",
            "--agent",
            agent_name,
            "--message",
            prompt
        ]
    else:
        # Claude 环境：使用原有的 claude 命令
        command = [
            "claude",
            "-p",
            prompt,
            "--allowedTools",
            "Bash, Read, Edit, Write, WebSearch, WebFetch, Skill",
            "--append-system-prompt",
            "你是一个专业的网上冲浪者，无法回答的问题请进行网络搜索，所有python脚本都要直接用python解释器+py文件执行，而不要用-c命令执行",
            "--output-format",
            "stream-json",
            "--verbose"
        ]

    try:
        # 调用命令
        if check_file_size(log_filename):
            # 在原日志文件名基础上添加时间戳进行备份
            base_name, ext = os.path.splitext(log_filename)
            backup_filename = f"{base_name}_{get_time_suffix()}{ext}"
            os.rename(log_filename, backup_filename)

        with open(log_filename, "a", encoding="utf-8") as f:
            # 写入 worker_id 信息
            if worker_id is not None:
                f.write(f"\n{'='*80}\n")
                f.write(f"[Worker ID: {worker_id}] 技能: {skill_name}\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"环境: {env_name}\n")
                if env_name == 'openclaw':
                    f.write(f"Agent名称: {agent_name}\n")
                f.write(f"输入数据: {json_data}\n")
                f.write(f"{'='*80}\n\n")

            # 执行命令，同时捕获 stdout 和 stderr
            # Linux 环境：取消设置 CLAUDECODE 环境变量以绕过嵌套调用检查，不使用 shell
            # Windows 环境：保持原样
            if sys.platform == 'win32':
                # Windows 环境
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,  # 防止因 stdin 问题立刻退出
                    stdout=f,
                    stderr=subprocess.STDOUT,  # 将 stderr 也重定向到 stdout
                    check=False,
                    shell=True,
                    timeout=MAX_TIME_OUT
                )
            else:
                # Linux/macOS 环境
                env = os.environ.copy()
                env.pop('CLAUDECODE', None)
                env.pop('CLAUDE_CODE', None)

                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,  # 防止因 stdin 问题立刻退出
                    stdout=f,
                    stderr=subprocess.STDOUT,  # 将 stderr 也重定向到 stdout
                    check=False,
                    shell=False,  # 不使用 shell，避免参数解析问题
                    env=env,
                    timeout=MAX_TIME_OUT
                )
        return result.returncode
    except FileNotFoundError:
        if env_name == 'openclaw':
            print("错误: 找不到 openclaw 命令，请确保 OpenClaw CLI 已安装并在系统路径中", file=sys.stderr)
        else:
            print("错误: 找不到 claude 命令，请确保 Claude CLI 已安装并在系统路径中", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("用法: python run_claude.py <skill_name> <json_data> [worker_id]", file=sys.stderr)
        print("示例: python run_claude.py my_skill '{\"key\": \"value\"}'", file=sys.stderr)
        sys.exit(1)

    skill_name = sys.argv[1]
    json_data = sys.argv[2]
    worker_id = sys.argv[3] if len(sys.argv) > 3 else None

    # 运行 Claude
    exit_code = run_claude(skill_name, json_data, worker_id)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
