try:
    # 모델 다운로드 시 Windows 인증서 저장소로 검증 (백신/프록시 환경의 SSL 오류 방지)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from .config import Settings
from .pipeline import run

__all__ = ["Settings", "run"]
