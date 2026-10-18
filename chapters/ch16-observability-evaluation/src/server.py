"""本番の入口。第13章の API に、構造化ログを足す。API のコード自体は変えない。"""
import observability
from api.main import app

observability.install(app)
