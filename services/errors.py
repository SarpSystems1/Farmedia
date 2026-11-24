"""Farmedia özel hata sınıfları.

Her hata şunları taşır:
    * ``status_code``: Yanıtta kullanılacak HTTP durum kodu.
    * ``error_code``: İstemcinin makine tarafından okuyabileceği sabit kod.
    * ``message_key``: ``services.i18n`` içindeki çeviri anahtarı.
    * ``detail``: Dil bağımsız, geliştirici odaklı varsayılan açıklama (log için).
    * ``params``: Çeviri metnindeki ``{placeholder}`` alanları için değerler.

FastAPI tarafında tek bir exception handler ile kullanım örneği:

    from fastapi import Request
    from fastapi.responses import JSONResponse
    from services.errors import BaseFarmediaError
    from services.i18n import t

    @app.exception_handler(BaseFarmediaError)
    async def farmedia_error_handler(request: Request, exc: BaseFarmediaError):
        lang = getattr(request.state, "lang", "tr")
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict(lang, t))
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Callable, ClassVar


class BaseFarmediaError(Exception):
    """Tüm Farmedia hatalarının temel sınıfı."""

    status_code: ClassVar[int] = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code: ClassVar[str] = "internal_error"
    message_key: ClassVar[str] = "error.internal"
    default_detail: ClassVar[str] = "Unexpected internal error."

    def __init__(
        self,
        detail: str | None = None,
        *,
        params: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.detail: str = detail or self.default_detail
        self.params: dict[str, Any] = params or {}
        # Gerekirse örnek bazında durum kodu geçersiz kılınabilir.
        if status_code is not None:
            self.status_code = status_code  # type: ignore[misc]
        super().__init__(self.detail)

    def to_dict(
        self,
        lang: str = "tr",
        translator: Callable[..., str] | None = None,
    ) -> dict[str, Any]:
        """Hatayı JSON'a uygun sözlüğe çevirir.

        ``translator`` verilirse (örn. ``services.i18n.t``) ``message`` alanı
        istenen dilde üretilir; verilmezse ``detail`` kullanılır.
        """
        if translator is not None:
            try:
                message = translator(lang, self.message_key, **self.params)
            except Exception:  # çeviri hatası asıl hatayı gizlememeli
                message = self.detail
        else:
            message = self.detail

        return {
            "error": {
                "code": self.error_code,
                "status": int(self.status_code),
                "message": message,
                "detail": self.detail,
            }
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(status_code={int(self.status_code)}, "
            f"error_code={self.error_code!r}, detail={self.detail!r})"
        )


class UpstreamTimeoutError(BaseFarmediaError):
    """Harici servis (Open-Meteo vb.) zaman aşımına uğradı."""

    status_code = HTTPStatus.GATEWAY_TIMEOUT  # 504
    error_code = "upstream_timeout"
    message_key = "error.upstream_timeout"
    default_detail = "The upstream service did not respond in time."


class UpstreamFailureError(BaseFarmediaError):
    """Harici servis hata döndürdü veya geçersiz yanıt verdi."""

    status_code = HTTPStatus.BAD_GATEWAY  # 502
    error_code = "upstream_failure"
    message_key = "error.upstream_failure"
    default_detail = "The upstream service returned an error or an invalid response."


class LocationNotFoundError(BaseFarmediaError):
    """Verilen konum geocoding servisinde bulunamadı."""

    status_code = HTTPStatus.NOT_FOUND  # 404
    error_code = "location_not_found"
    message_key = "error.location_not_found"
    default_detail = "The requested location could not be found."

    def __init__(self, query: str | None = None, detail: str | None = None) -> None:
        params = {"query": query} if query else {}
        if detail is None and query:
            detail = f"Location not found: {query!r}"
        super().__init__(detail, params=params)
        self.query = query


class InvalidInputError(BaseFarmediaError):
    """İstemciden gelen girdi geçersiz (koordinat aralığı, boş sorgu vb.)."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY  # 422
    error_code = "invalid_input"
    message_key = "error.invalid_input"
    default_detail = "The provided input is invalid."

    def __init__(self, detail: str | None = None, *, field: str | None = None) -> None:
        params = {"field": field} if field else {}
        super().__init__(detail, params=params)
        self.field = field


__all__ = [
    "BaseFarmediaError",
    "UpstreamTimeoutError",
    "UpstreamFailureError",
    "LocationNotFoundError",
    "InvalidInputError",
]