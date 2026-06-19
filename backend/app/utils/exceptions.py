"""业务异常与统一错误码。"""
from __future__ import annotations


class BizError(Exception):
    """业务异常：由全局异常处理器转成统一响应体。"""

    def __init__(self, message: str, code: int = 4000, http_status: int = 400):
        self.message = message
        self.code = code
        self.http_status = http_status
        super().__init__(message)


class AuthError(BizError):
    def __init__(self, message: str = "登录状态已失效，请重新登录"):
        super().__init__(message, code=4010, http_status=401)


class PermissionError_(BizError):
    def __init__(self, message: str = "无权访问该资源"):
        super().__init__(message, code=4030, http_status=403)


class NotFoundError(BizError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, code=4040, http_status=404)


class ConflictError(BizError):
    def __init__(self, message: str = "业务冲突"):
        super().__init__(message, code=4090, http_status=409)


class StateMachineError(BizError):
    def __init__(self, message: str = "当前状态不允许该操作"):
        super().__init__(message, code=4091, http_status=409)
