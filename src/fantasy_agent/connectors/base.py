from abc import ABC, abstractmethod
from typing import Optional
from ..models.player import Player
from ..models.roster import Roster


class BaseConnector(ABC):

    @abstractmethod
    def get_my_roster(self, week: int) -> Roster:
        ...

    @abstractmethod
    def get_free_agents(
        self,
        week: int,
        position: Optional[str] = None,
        limit: int = 50,
    ) -> list[Player]:
        ...

    @abstractmethod
    def get_matchup(self, week: int) -> dict:
        ...

    @abstractmethod
    def get_current_week(self) -> int:
        ...
