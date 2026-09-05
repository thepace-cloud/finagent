# 三个黑盒，你暂时不用管它们内部怎么实现：
# chat(messages, stop=["Observation:"]) -> str      # 模型说一句话
# parse_action(reply) -> (thought, action, arg)     # 解析出动作（无动作时 action=None）
# dispatch(action, arg) -> str                      # 执行工具，返回结果
import re

from llm import chat
from tools import dispatch, docs
ACTION_RE = re.compile(r"Action:\s*(\w+)\s*\[(.*?)\]", re.DOTALL)
SYSTEM_PROMPT = f"""You are a ReAct agent. Answer questions by interleaving short Thoughts and Actions.

Available actions:
{docs()}

OUTPUT FORMAT (every assistant message must follow this exactly):
Thought: <one short sentence of reasoning>
Action: <action_name>[<input>]

After writing one Action, STOP. The environment will reply with an Observation as a user message. Then continue with another Thought / Action. When you have the final answer, use finish[...]. If a tool can answer part of a question, use it first instead of answering from memory.
"""



def parse_action(text: str) -> tuple[str, str | None, str | None]:
    """Split an assistant reply into (thought, action_name, action_arg).

    Returns (text, None, None) when no Action is found — the caller treats
    that as the final answer (model decided to talk instead of act).
    """
    match = ACTION_RE.search(text)
    if not match:
        return text.strip(), None, None
    thought = text[: match.start()]
    thought = re.sub(r"^\s*Thought:\s*", "", thought, count=1).strip()
    return thought, match.group(1), match.group(2).strip()
def agent_turn(messages: list[dict], max_steps: int = 8) -> str:
    for step in range(1, max_steps + 1):
        reply=chat(messages,stop=["Observation:"])
        messages.append({"role": "assistant", "content": reply})
        thought,action,arg=parse_action(reply)
        if action is None:
             print(f"  [step {step}] (no action - using reply as final)")
             return thought or reply.strip()
        print(f"  [step {step}] action:  {action}[{arg}]")
        if action == "finish":
            return arg
        try:
            observation = dispatch(action, arg)
        except Exception as exc:
            observation = f"Error from {action}: {exc}"
        preview = observation[:120] + ("..." if len(observation) > 120 else "")
        print(f"  [step {step}] observ:  {preview}")

        messages.append({"role": "user", "content": f"Observation: {observation}"})

    return "(stopped: max_steps reached without finish)"
if __name__ == "__main__":
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "用工具算一下 137 加 89 等于多少"},
    ]
    answer = agent_turn(messages)
    print(f"\nassistant> {answer}")
    
        

       