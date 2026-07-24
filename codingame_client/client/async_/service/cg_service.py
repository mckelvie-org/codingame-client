"""Service endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from json_data_types import JsonData

if TYPE_CHECKING:
    from ..client import CgAsyncClient

__all__ = [
    "CgAsyncService",
]

class CgAsyncService:
    """Base class for a service endpoint."""
    
    client: CgAsyncClient
    
    service_name: str

    def __init__(self, client: CgAsyncClient, service_name: str) -> None:
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
