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
    from winrt.windows.devices.bluetooth.advertisement import (
        BluetoothLEAdvertisementPublisher,
        BluetoothLEAdvertisementDataSection,
        BluetoothLEAdvertisement,
    )
    from winrt.windows.storage.streams import DataWriter
    from typing import Any, cast
    from zeroconf import DNSQuestionType

from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
)

from ..common import create_task, tasks

BLE_GAP_AD_TYPE_SERVICE_DATA = 0x16  # Service Data - 16-bit UUID.
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
        
        # Service UUID (16-bit): FE2C -> Little Endian
        uuid_fe2c = b'\x2C\xFE'
        
        # Service Data:
        service_data = bytes.fromhex("fc128e014200000000000000000001020304050607080910")
        
        # Full Service Data payload: UUID + Service Data
        service_data_payload = uuid_fe2c + service_data
        
        # Create DataWriter and buffer
        writer = DataWriter()
        writer.write_bytes(service_data_payload)
        buffer = writer.detach_buffer()
        
        # Create BLE advertisement
        advertisement = BluetoothLEAdvertisement()
        
        # Add the service data section
        service_data_section = BluetoothLEAdvertisementDataSection(
            BLE_GAP_AD_TYPE_SERVICE_DATA,
            buffer
        )
        advertisement.data_sections.append(service_data_section)

        # Create and start the BLE advertisement publisher
        publisher = BluetoothLEAdvertisementPublisher(advertisement)
        publisher.start()
        bluetooth.debug("BLE advertising started.")

        try:
            while True:
                await asyncio.sleep(1)
        except:
            publisher.stop()
            print("BLE advertising stopped.")
    
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

    if os_name == "Linux":
        runner = AsyncRunner()

        task = create_task(runner.async_run())
        _tasks.append(task)

        return runner.result
    elif os_name == "Windows":
        # Create and set a new event loop as loop = asyncio.get_event_loop() is deprecated in Python 3.11
        # loop = asyncio.new_event_loop()
        # asyncio.set_event_loop(loop)
        runner = AsyncRunnerWindows()
        # try:
        #     loop.run_until_complete(runner.async_run())
        # except:
        #     loop.run_until_complete(runner.async_close())
        task = create_task(runner.async_run())
        _tasks.append(task)
        return runner.result


@atexit.register
def cleanup() -> None:
    if _tasks:
        logger.debug("Shutting advertiser and browser down")

    for task in _tasks:
        task.cancel()

DEVICE_INFO_SERVICE: str = "_device-info._tcp.local."
QUICK_SHARE: str = "_FC9F5ED42C8A._tcp.local."

ALL_SERVICES = [
    QUICK_SHARE
]

log = getLogger(__name__)

_PENDING_TASKS: set[asyncio.Task] = set()

class AsyncRunnerWindows:
    def __init__(self) -> None:
        self.result: asyncio.Queue[AsyncServiceInfo] = asyncio.Queue()
        self.aiobrowser: AsyncServiceBrowser | None = None
        self.aiozc: AsyncZeroconf | None = None

    async def async_run(self) -> None:
        self.aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        await self.aiozc.zeroconf.async_wait_for_start()
        print(f"\nBrowsing {ALL_SERVICES} service(s), press Ctrl-C to exit...\n")
        kwargs = {
            "handlers": [self.async_on_service_state_change],
            "question_type": DNSQuestionType.QU,
        }
        # if self.args.target:
        #     kwargs["addr"] = self.args.target
        self.aiobrowser = AsyncServiceBrowser(
            self.aiozc.zeroconf,
            ALL_SERVICES,
            **kwargs,  # type: ignore[arg-type]
        )
        await asyncio.Event().wait()

    async def async_close(self) -> None:
        assert self.aiozc is not None
        assert self.aiobrowser is not None
        await self.aiobrowser.async_cancel()
        await self.aiozc.async_close()
    
    def async_on_service_state_change(self, 
        zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ) -> None:
        logger.debug("Discovered Quick Share service: %s with state changed: %s", name, state_change)
        if state_change is not ServiceStateChange.Added:
            return
        base_name = name[: -len(service_type) - 1]
        device_name = f"{base_name}.{DEVICE_INFO_SERVICE}"
        task = asyncio.ensure_future(self._async_show_service_info(zeroconf, service_type, name))
        _PENDING_TASKS.add(task)
        task.add_done_callback(_PENDING_TASKS.discard)
        # Also probe for device info
        task = asyncio.ensure_future(self._async_show_service_info(zeroconf, DEVICE_INFO_SERVICE, device_name))
        _PENDING_TASKS.add(task)
        task.add_done_callback(_PENDING_TASKS.discard)
    
    async def _async_show_service_info(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        await info.async_request(zeroconf, 3000, question_type=DNSQuestionType.QU)
        if info:
            await self.result.put(info)
        else:
            logger.debug("  No info")