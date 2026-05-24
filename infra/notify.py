# ============================================================
# infra/notify.py — Webhook 通知（企业微信/飞书/自定义）
# ============================================================
import json
import logging
import os
import urllib.request
from datetime import datetime

logger = logging.getLogger("infra.notify")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_TYPE = os.getenv("WEBHOOK_TYPE", "generic")  # wecom | feishu | generic

# 最近通知记录（内存，重启清空）
_notification_log = []  # [{time, title, status, error}]
MAX_LOG = 50


def _build_payload(title, body, status):
    """根据 webhook 类型构建消息体"""
    icon = {"success": "✅", "fail": "❌", "start": "⏳"}.get(status, "📋")
    text = f"{icon} **{title}**\n{body}\n_{datetime.now().strftime('%m-%d %H:%M')}_"

    if WEBHOOK_TYPE == "wecom":
        return json.dumps({
            "msgtype": "markdown",
            "markdown": {"content": text},
        }).encode("utf-8")
    elif WEBHOOK_TYPE == "feishu":
        return json.dumps({
            "msg_type": "text",
            "content": {"text": text},
        }).encode("utf-8")
    else:
        return json.dumps({"title": title, "body": body, "status": status, "time": datetime.now().isoformat()}).encode("utf-8")


def send(title, body="", status="success"):
    """发送 webhook 通知"""
    global _notification_log

    _notification_log.append({
        "time": datetime.now().isoformat(),
        "title": title[:100],
        "status": status,
        "error": "",
    })
    if len(_notification_log) > MAX_LOG:
        _notification_log = _notification_log[-MAX_LOG:]

    if not WEBHOOK_URL:
        logger.debug("[notify] WEBHOOK_URL 未配置，跳过通知")
        return False

    try:
        payload = _build_payload(title, body, status)
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("[notify] sent: %s (%s)", title[:40], status)
            return True
    except Exception as e:
        logger.warning("[notify] 发送失败: %s", e)
        if _notification_log:
            _notification_log[-1]["error"] = str(e)[:100]
        return False


def get_recent(limit=20):
    """获取最近通知记录"""
    return _notification_log[-limit:]


def notify_task_result(topic, score, elapsed, success=True):
    """便捷：通知定时任务结果"""
    status = "success" if success else "fail"
    title = f"推广任务{'完成' if success else '失败'}: {topic[:30]}"
    body = f"评分: {score}/100 | 耗时: {elapsed}s" if success else f"错误: {elapsed}"
    send(title, body, status)
