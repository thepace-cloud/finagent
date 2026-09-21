"""V5 重试护栏 —— 给不可靠的外部调用（LLM/网络）包一层有上限的重试

拷问主线：重试与降级的分工
  这里管的是「调用失败」的超时/网络抖动——瞬间性故障，重试合理；
  v5_validator 管的是「结果不对」的内容校验——带反馈重生成，另一条线。
  两条线都有上限：这里是 LLM_RETRIES 次，那边 1 次——护栏纪律不重不漏。

为什么不装 tenacity 库：手写 15 行能讲清楚重试的每个细节
（次数、间隔、哪些异常才重试），装库反而讲不清（红线：不引入拷问守不住的）。
"""
import logging
import time

logger = logging.getLogger("finagent.retry")


def with_retry(fn, label: str, retries: int, delay: float,
               retry_on=(Exception,)):
    """包一个函数：失败按 retry_on 过滤后重试，最多 retries 次。

    只重试 retry_on 里的异常类型——参数错误这种必然复现的失败，
    重试一万次也一样，快速失败才是正解。
    """
    def wrapped(*args, **kwargs):
        last = None
        for attempt in range(retries + 1):          # 1 次首发 + N 次重试
            try:
                return fn(*args, **kwargs)
            except retry_on as exc:
                last = exc
                if attempt < retries:
                    logger.warning("%s 第%d次失败(%s: %s)，%.1fs 后重试",
                                   label, attempt + 1,
                                   exc.__class__.__name__, exc, delay)
                    time.sleep(delay)
        raise last                                   # 重试用尽：把最后一次异常抛出去
    return wrapped
