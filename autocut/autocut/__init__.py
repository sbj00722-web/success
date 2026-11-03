try:
    # 모델 다운로드 시 Windows 인증서 저장소로 검증 (백신/프록시 환경의 SSL 오류 방지)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import os

from dotenv import load_dotenv

# autocut/.env 의 API 키를 환경변수로 (이미 설정된 값은 덮어쓰지 않음)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

from .config import Settings
from .pipeline import run

__all__ = ["Settings", "run"]
