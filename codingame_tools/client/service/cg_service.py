"""Service endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar

from json_data_types import JsonData

if TYPE_CHECKING:
    from ..client import CgClient

__all__ = [
    "CgService",
    "CgServiceHelper",
]

class CgService:
    """Base class for a service endpoint."""
    
    client: CgClient
    
    service_name: str

    def __init__(self, client: CgClient, service_name: str) -> None:
        self.client = client
        self.service_name = service_name
        
    async def service_request(
                self,
                func_name: str,
                args: list[JsonData] | None = None,
                *,
                require_login: bool = True
            ) -> JsonData:
        """Make a service request to the CodinGame API.
        
        Args:
            func_name: The name of the service function to call.
            args: The arguments to pass to the service function. Defaults to an empty list.
            require_login: Whether the request requires a valid login. Defaults to True.
            
        Returns:
            The decoded JSON response from the service function.
        """
        return await self.client.service_request(
                self.service_name, func_name, args, require_login=require_login
            )
        
    async def service_request_to_dict(
                self,
                func_name: str,
                args: list[JsonData] | None = None,
                *,
                require_login: bool = True
            ) -> dict[str, JsonData]:
        """Make a service request to the CodinGame API and return the response as a dict.
        
        Args:
            func_name: The name of the service function to call.
            args: The arguments to pass to the service function. Defaults to an empty list.
            require_login: Whether the request requires a valid login. Defaults to True.
            
        Returns:
            The decoded JSON response from the service function as a dict.
        """
        return  await self.client.service_request_to_dict(
                self.service_name, func_name, args, require_login=require_login
            )
        
    async def service_request_to_list(
                self,
                func_name: str,
                args: list[JsonData] | None = None,
                *,
                require_login: bool = True
            ) -> list[JsonData]:
        """Make a service request to the CodinGame API and return the response as a list.
        
        Args:
            func_name: The name of the service function to call.
            args: The arguments to pass to the service function. Defaults to an empty list.
            require_login: Whether the request requires a valid login. Defaults to True.
            
        Returns:
            The decoded JSON response from the service function as a list.
        """
        return await self.client.service_request_to_list(
                self.service_name, func_name, args, require_login=require_login
            )
        
    async def require_authenticate(self) -> None:
        """Ensure that the client is authenticated, logging in if necessary."""
        await self.client.require_authenticate()


TService = TypeVar("TService", bound=CgService)


class CgServiceHelper(Generic[TService]):
    """Base class for a service endpoint's helper object.

       Helper objects provide higher-level convenience methods for a service--e.g. retry/polling
       logic or normalized wrappers built on top of one or more of the service's own calls--without
       needing a whole parallel module hierarchy alongside the service classes. Helper methods must
       never do anything a caller could not already do with the service's own public methods; there
       is no special access or hidden behavior here, just more convenient combinations of already-
       public building blocks.

       Every service exposes a `.helper` attribute of its own dedicated helper subclass, even one
       that (like this base class) currently has no extra methods--so the attribute's presence and
       static type never change later just because functionality is added to it.

       Generic over `TService` (bound to `CgService`) so that each service's helper subclass
       need only parameterize this base class with its own service type--e.g.
       `class CgContributionServiceHelper(CgServiceHelper["CgContributionService"])`--
       to get a correctly, statically narrowed `self.service` with no `__init__` override and no
       unchecked attribute redeclaration. Any methods added here on the base class are themselves
       generic over `TService` and thus usable from every helper subclass unchanged.
    """

    service: TService
    """The service endpoint instance this helper is attached to."""

    def __init__(self, service: TService) -> None:
        self.service = service

    @property
    def client(self) -> CgClient:
        """The client through which the owning service makes endpoint requests."""
        return self.service.client
