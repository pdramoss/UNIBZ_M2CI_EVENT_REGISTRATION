"""The base every request and response model inherits.

``extra="forbid"`` is the API's contract: an unknown field is a 422, not a
silently ignored key. Each service defines its own models on top of this in its
own ``schemas.py``.
"""

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
