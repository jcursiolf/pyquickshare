import asyncio
import atexit
import binascii
import platform
import random
from logging import getLogger
from typing import Any

os_name = platform.system()

if os_name == "Linux":
    from bless.backends.bluezdbus.dbus.advertisement import BlueZLEAdvertisement, Type
    from bless.backends.bluezdbus.server import BlessServerBlueZDBus
    from dbus_next.signature import Variant
elif os_name == "Windows":
    # How to make advertisement?
    #from bless.backends.winrt.server import BlessServerWinRT
    from bless import GATTCharacteristicProperties, GATTAttributePermissions, BlessServer
from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
)

from ..common import create_task, tasks

SERVICE_UUID = "FE2C"
SERVICE_DATA = binascii.unhexlify("fc128e0142000000000000000000")

logger = getLogger(__name__)
bluetooth = logger.parent.getChild(  # pyright: ignore[reportOptionalMemberAccess]
    "bluetooth",
)


_tasks: list[asyncio.Task[Any]] = []


class AsyncRunner:
    def __init__(self) -> None:
        self.result: asyncio.Queue[AsyncServiceInfo] = asyncio.Queue()
        self.aiobrowser: AsyncServiceBrowser | None = None
        self.aiozc: AsyncZeroconf | None = None

    async def async_run(self) -> None:
        self.aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)

        services = ["_FC9F5ED42C8A._tcp.local."]
        self.aiobrowser = AsyncServiceBrowser(
            self.aiozc.zeroconf,
            services,
            handlers=[self.async_on_service_state_change],
        )
        await asyncio.Event().wait()

    async def async_close(self) -> None:
        assert self.aiozc is not None  # noqa: S101 - escape hatch for the type checker
        assert self.aiobrowser is not None  # noqa: S101 - escape hatch for the type checker
        await self.aiobrowser.async_cancel()
        await self.aiozc.async_close()

    def async_on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        logger.debug("Discovered Quick Share service: %s", name)

        # make sure this gets cleaned up properly
        tasks.append(
            asyncio.ensure_future(
                self.async_display_service_info(zeroconf, service_type, name),
            ),
        )

    async def async_display_service_info(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
    ) -> None:
        info = AsyncServiceInfo(service_type, name)
        await info.async_request(zeroconf, 3000)

        if info:
            await self.result.put(info)


async def trigger_devices() -> None:
    if os_name == "Windows":
        # I actually have less than zero clue what I'm doing here`
        bluetooth.debug("It is windows!")
        server = BlessServer(name="pyquickshare_windows")
        
        #THERE IS NO SETUP_TASK FOR THE WINRT SERVER
        #await server.setup_task  # pyright: ignore[reportUnknownMemberType]
        
        bluetooth.debug("Connected to whatever WinRT uses")

        # THERE IS NO server.app THE WINRT SERVER
        # await server.app.set_name(server.adapter, server.name)
        
        # THERE IS NO BlueZLEAdvertisement EQUIVALENT FOR THE  WINRT SERVER
        # Type.BROADCAST is defined in bless\backends\bluezdbus\dbus\advertisement.py and has no counterpart in WinRT
        # There is no server.app in the WinRT server
        # advertisement = BlueZLEAdvertisement(Type.BROADCAST, 2, server.app)

        # HOW DO I PASS THE SERVICE_UUID to WinRT???
        # advertisement.ServiceUUIDs = [SERVICE_UUID]S

        # from https://github.com/Martichou/rquickshare/blob/master/core_lib/src/hdl/ble.rs
        SERVICE_UUID_SHARING = "0000fe2c-0000-1000-8000-00805f9b34fb"
        
        await server.add_new_service(uuid=SERVICE_UUID_SHARING)
        bluetooth.debug(f"Added new service with UUID {SERVICE_UUID_SHARING}")
        
        
        # HOW DO I PASS THE SERVICE_DATA to WinRT???
        # Variant is defined on dbus_next\signature.py and clearly on Windows.
        # advertisement.ServiceData = {
        #     SERVICE_UUID: Variant("ay", SERVICE_DATA + random.randbytes(9)),  # noqa: S311 - random is fine here
        # }

        # Add a Characteristic to the service
        # I have no idea what to put in the char uuid
        service_char_uuid = "51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B"
        
        # I think just broadcast would be enough, but who knows?
        service_properties = (
            GATTCharacteristicProperties.read |
            GATTCharacteristicProperties.write |
            GATTCharacteristicProperties.indicate
            )

        # NRF Connect says the Linux version has no flags....
        service_properties = 0
        
        # Got this from https://github.com/rohitsangwan01/ble_peripheral_windows/blob/main/python/ble__handler.py
        service_permissions = (
            GATTAttributePermissions.readable |
            GATTAttributePermissions.writeable
        )
        
        # What should the service value be?
        service_data_value = SERVICE_DATA + random.randbytes(9)
        bluetooth.debug("Service value?")
        
        await server.add_new_characteristic(
            service_uuid=SERVICE_UUID_SHARING,
            char_uuid=service_char_uuid,
            properties=service_properties,
            value=None,
            permissions=service_permissions
            )
        bluetooth.debug(f"Characteristics added! {server.get_characteristic(service_char_uuid)}")

        
        # server.app.advertisements = [advertisement]

        # server.bus.export(advertisement.path, advertisement)

        # There is no server.adapter in WinRT backend.
        # iface = server.adapter.get_interface("org.bluez.LEAdvertisingManager1")

        # await iface.call_register_advertisement(  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            # advertisement.path,
            # {},
        # )

        await server.start()
        bluetooth.debug("Advertising Quick Share service")

        # Wait forever, BlueZ keeps advertising while the D-Bus connection is open
    
    elif os_name == "Linux":
        # I actually have zero clue what I'm doing here

        server = BlessServerBlueZDBus(name="pyquickshare_linux")
        await server.setup_task  # pyright: ignore[reportUnknownMemberType]
        bluetooth.debug("Connected to BlueZ D-Bus")  # Hello :3

        await server.app.set_name(server.adapter, server.name)
        advertisement = BlueZLEAdvertisement(Type.BROADCAST, 2, server.app)

        advertisement.ServiceUUIDs = [SERVICE_UUID]
        advertisement.ServiceData = {
            SERVICE_UUID: Variant("ay", SERVICE_DATA + random.randbytes(9)),  # noqa: S311 - random is fine here
        }

        server.app.advertisements = [advertisement]

        server.bus.export(advertisement.path, advertisement)

        iface = server.adapter.get_interface("org.bluez.LEAdvertisingManager1")

        await iface.call_register_advertisement(  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            advertisement.path,
            {},
        )

        bluetooth.debug("Advertising Quick Share service")

        # Wait forever, BlueZ keeps advertising while the D-Bus connection is open
    await asyncio.Future()


async def discover_services(timeout: float = 10) -> asyncio.Queue[AsyncServiceInfo]:  # noqa: ARG001 # TODO: actually timeout
    task = create_task(trigger_devices())
    _tasks.append(task)

    runner = AsyncRunner()

    task = create_task(runner.async_run())
    _tasks.append(task)

    return runner.result


@atexit.register
def cleanup() -> None:
    if _tasks:
        logger.debug("Shutting advertiser and browser down")

    for task in _tasks:
        task.cancel()
