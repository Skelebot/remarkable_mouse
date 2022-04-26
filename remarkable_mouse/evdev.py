import logging
import struct
import subprocess
from screeninfo import get_monitors
import time
from itertools import cycle
from socket import timeout as TimeoutError
import libevdev

from .codes import EV_SYN, EV_ABS, ABS_X, ABS_Y, SYN_REPORT
from .common import get_monitor, remap, wacom_width, wacom_height

logging.basicConfig(format='%(message)s')
log = logging.getLogger('remouse')

def create_local_device():
    """
    Create a virtual input device on this host that has the same
    characteristics as a Wacom tablet.

    Returns:
        virtual input device
    """
    import libevdev
    device = libevdev.Device()

    # Set device properties to emulate those of Wacom tablets
    device.name = 'reMarkable pen'

    device.id = {
        'bustype': 0x03, # usb
        'vendor': 0x056a, # wacom
        'product': 0,
        'version': 54
    }

    # Enable buttons supported by the digitizer
    device.enable(libevdev.EV_KEY.BTN_TOOL_PEN)
    device.enable(libevdev.EV_KEY.BTN_TOOL_RUBBER)
    device.enable(libevdev.EV_KEY.BTN_TOUCH)
    device.enable(libevdev.EV_KEY.BTN_STYLUS)
    device.enable(libevdev.EV_KEY.BTN_STYLUS2)
    device.enable(libevdev.EV_KEY.BTN_0)
    device.enable(libevdev.EV_KEY.BTN_1)
    device.enable(libevdev.EV_KEY.BTN_2)

    inputs = (
        # touch inputs
        (libevdev.EV_ABS.ABS_MT_POSITION_X,  0,    20967, 2531),
        (libevdev.EV_ABS.ABS_MT_POSITION_Y,  0,    15725, 2531),
        (libevdev.EV_ABS.ABS_MT_PRESSURE,    0,    255,   None),
        (libevdev.EV_ABS.ABS_MT_TOUCH_MAJOR, 0,    255,   None),
        (libevdev.EV_ABS.ABS_MT_TOUCH_MINOR, 0,    255,   None),
        (libevdev.EV_ABS.ABS_MT_ORIENTATION, -127, 127,   None),
        (libevdev.EV_ABS.ABS_MT_SLOT,        0,    31,    None),
        (libevdev.EV_ABS.ABS_MT_TOOL_TYPE,   0,    1,     None),
        (libevdev.EV_ABS.ABS_MT_TRACKING_ID, 0,    65535, None),

        # pen inputs
        (libevdev.EV_ABS.ABS_X,        0,     767,  2531), # cyttps5_mt driver
        (libevdev.EV_ABS.ABS_Y,        0,     1023, 2531), # cyttsp5_mt
        (libevdev.EV_ABS.ABS_PRESSURE, 0,     4095, None),
        (libevdev.EV_ABS.ABS_DISTANCE, 0,     255,  None),
        (libevdev.EV_ABS.ABS_TILT_X,   -9000, 9000, None),
        (libevdev.EV_ABS.ABS_TILT_Y,   -9000, 9000, None)
    )

    for code, minimum, maximum, resolution in inputs:
        device.enable(
            code,
            libevdev.InputAbsInfo(
                minimum=minimum, maximum=maximum, resolution=resolution
            )
        )

    return device.create_uinput_device()


def read_tablet(rm_inputs, *, orientation, monitor_num, region, threshold, mode):
    """Pipe rM evdev events to local device

    Args:
        rm_inputs (dictionary of paramiko.ChannelFile): dict of pen, button
            and touch input streams
        orientation (str): tablet orientation
        monitor_num (int): monitor number to map to
        threshold (int): pressure threshold
        mode (str): mapping mode
    """

    local_device = create_local_device()
    log.debug("Created virtual input device '{}'".format(local_device.devnode))

    monitor = get_monitor(region, monitor_num, orientation)

    pending_events = []

    x = y = 0

    # loop inputs forever
    # for input_name, stream in cycle(rm_inputs.items()):
    stream = rm_inputs['pen']
    while True:
        try:
            data = stream.read(16)
        except TimeoutError:
            continue

        e_time, e_millis, e_type, e_code, e_value = struct.unpack('2IHHi', data)

        e_bit = libevdev.evbit(e_type, e_code)
        e = libevdev.InputEvent(e_bit, value=e_value)

        local_device.send_events([e])

        if e_type == EV_ABS:

            # handle x direction
            if e_code == ABS_Y:
                x = e_value

            # handle y direction
            if e_code == ABS_X:
                y = e_value

        elif e_type == EV_SYN:
            mapped_x, mapped_y = remap(
                x, y,
                wacom_width, wacom_height,
                monitor.width, monitor.height,
                mode, orientation
            )
            local_device.send_events([e])
            print('sent')
            print(e_type)

        else:
            local_device.send_events([e])

        # While debug mode is active, we log events grouped together between
        # SYN_REPORT events. Pending events for the next log are stored here
        # if log.level == logging.DEBUG:
        #     if e_bit == SYN_REPORT:
        #         event_repr = ', '.join(
        #             '{} = {}'.format(
        #                 e.code.name,
        #                 e.value
        #             ) for event in pending_events
        #         )
        #         log.debug('{}.{:0>6} - {}'.format(e_time, e_millis, event_repr))
        #         pending_events = []
        #     else:
        #         pending_events.append(event)
