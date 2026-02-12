"""Dependency composition root."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.chat_service import chat_service
from app.application.item_label_service import ItemLabelApplicationService
from app.application.market_service import MarketApplicationService
from app.data import default_market_service
from app.data.dump_manager import DumpManager
from app.data.game_database import default_game_database
from app.data.history_db import HistoryDatabase
from app.data.item_resolver import smart_resolver


@dataclass(frozen=True)
class AppContainer:
    """Wired application dependencies."""

    chat: Any
    market: MarketApplicationService
    item_labels: ItemLabelApplicationService
    history_db: HistoryDatabase
    dump_manager: DumpManager
    game_db: Any


_CONTAINER: AppContainer | None = None


def get_container() -> AppContainer:
    global _CONTAINER
    if _CONTAINER is not None:
        return _CONTAINER

    history_db = HistoryDatabase()
    dump_manager = DumpManager(db=history_db)
    market_app = MarketApplicationService(
        market_service=default_market_service,
        history_db=history_db,
        dump_manager=dump_manager,
        item_resolver=smart_resolver,
    )
    labels = ItemLabelApplicationService(game_db=default_game_database)

    _CONTAINER = AppContainer(
        chat=chat_service,
        market=market_app,
        item_labels=labels,
        history_db=history_db,
        dump_manager=dump_manager,
        game_db=default_game_database,
    )
    return _CONTAINER
