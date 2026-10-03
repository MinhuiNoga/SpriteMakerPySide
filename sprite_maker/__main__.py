from . import app
from .bootstrap_v4 import install


install(app)
raise SystemExit(app.run())
