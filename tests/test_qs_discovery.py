import argparse
import asyncio
import contextlib
import logging
import socket

import pyquickshare
from pyquickshare.common import Type, from_url64

nearby = logging.getLogger(__name__).getChild("nearby")

def convert_to_ipv4(addresses):
    return [socket.inet_ntoa(addr) for addr in addresses]

def get_qs_service_details(service):
    
    # Getting service name
    name = service.name.split(".")[0].lstrip("_")
    decoded = from_url64(name)
    peer_endpoint_id = decoded[1:5].decode("ascii")

    nearby.debug("Discovered endpoint %r", peer_endpoint_id)

    n_raw = service.properties.get(b"n")

    if n_raw is None:
        nearby.debug("No n record found, aborting")
        return None, None, None

    n = from_url64(n_raw.decode("utf-8"))
    flags = n[0]
    name = n[18:].decode("utf-8")

    # Getting type
    type = Type(flags >> 1 & 0b00000111)
    
    # Getting IPv4 from 2 possible sources
    ipv4_raw = service.properties.get(b"IPv4")
    first_ipv4_address = convert_to_ipv4(service.addresses)[0]
    ipv4 = ipv4_raw.decode("utf-8") if ipv4_raw is not None else first_ipv4_address

    # Debugging
    nearby.debug("Endpoint %r has name %r and type %r and ipv4 %r", peer_endpoint_id, name, type, ipv4)

    return name, type, ipv4

async def qs_discovery(timeout = 5) -> list:
    print(f"Discovering will last {timeout} seconds")
    discovered_services = []

    async def discover():
        async for service in pyquickshare.discover_services():
            discovered_services.append(service)
    try:
        await asyncio.wait_for(discover(), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"Discovery timed out after {timeout} seconds")
    
    return discovered_services

if __name__ == "__main__":
    print("Quick Share Discovery Test")
    print("==========================")

    # Arranging arguments
    parser = argparse.ArgumentParser(description="Tests the discovery of devices using Google's QuickShare")
    parser.add_argument('--debug', action='store_true', help="Enables debug logging")
    args = parser.parse_args()

    # Set logging level
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s - Line: %(lineno)d')
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Running discovery and printing results
    with contextlib.suppress(KeyboardInterrupt):
        qs_discovery_timeout = 10
        
        discovered_svcs = asyncio.run(qs_discovery(timeout=qs_discovery_timeout))
        for service in discovered_svcs:
            name, type, ipv4 = get_qs_service_details(service=service)
            if type != None:
                print(f"Found device {name} of type {type} with IPv4 {ipv4}")