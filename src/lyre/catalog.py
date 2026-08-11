from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from lyre.models import Conversation, Provider


class ConversationStore(Protocol):
    def scan(self) -> list[Conversation]: ...


class CompositeStore:
    """Merge provider catalogs into one recency-ordered conversation list."""

    def __init__(self, stores: Iterable[ConversationStore]) -> None:
        self.stores = tuple(stores)

    def scan(self) -> list[Conversation]:
        conversations: dict[tuple[Provider, str], Conversation] = {}
        for store in self.stores:
            for conversation in store.scan():
                existing = conversations.get(conversation.catalog_key)
                if existing is None or conversation.updated_at > existing.updated_at:
                    conversations[conversation.catalog_key] = conversation
        return sorted(
            conversations.values(), key=lambda item: item.updated_at, reverse=True
        )
