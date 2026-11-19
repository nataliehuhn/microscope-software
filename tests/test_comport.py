"""Serial framing regression tests; no microscope or serial port is opened."""
from collections import deque
from unittest.mock import patch

import pytest

from leica_microscope.includes.comport import (
    PersistentCommandSession, ParError, SequenceError, FlowError, MicroscopeError,
)


class FragmentedSerial:
    def __init__(self, chunks):
        self.chunks = deque(chunks)
        self.writes = []
        self.clock = 0.0

    def write(self, command):
        self.writes.append(command)

    def read_until(self, terminator):
        assert terminator == b"\r"
        self.clock += 0.01
        return self.chunks.popleft() if self.chunks else b""


def query(chunks, command="71023", output_format=int):
    session = PersistentCommandSession("SIMULATED")
    session.ser = FragmentedSerial(chunks)
    with patch("leica_microscope.includes.comport.time.perf_counter",
               side_effect=lambda: session.ser.clock):
        result = session.query(command, output_format, timeout=0.5)
    assert session.ser.writes == [command.rstrip("\r") + "\r"]
    return result


@pytest.mark.parametrize("split", range(1, len(b"71023 1130242\r")))
def test_reply_split_at_every_byte(split):
    reply = b"71023 1130242\r"
    assert query([reply[:split], b"", reply[split:]]) == 1130242


def test_reply_arriving_one_byte_at_a_time():
    assert query([bytes([b]) for b in b"71023 -12345\r"]) == -12345


@pytest.mark.parametrize("noise", [b"7\r", b"71\r", b"7102\r", b"garbage\r",
                                  b"\xff\r", b"71023 invalid\r", b"71023\r",
                                  b"\r\n", b"72023 99\r", b"71022\r"])
def test_bad_or_unrelated_frames_before_valid_reply(noise):
    assert query([noise, b"71023 12345\r"]) == 12345


def test_multiple_frames_and_partial_tail_in_one_read():
    assert query([b"71022\r71\r71023 12", b"345\r"]) == 12345


@pytest.mark.parametrize("chunks", [[], [b"7"], [b"71023 123"], [b"71\r"]])
def test_missing_complete_reply_times_out_instead_of_returning_partial_position(chunks):
    with pytest.raises(TimeoutError, match="complete valid reply.*71023.*SIMULATED"):
        query(chunks)


@pytest.mark.parametrize("code,exception", [(1, ParError), (2, SequenceError),
                                           (3, FlowError), (9, MicroscopeError)])
def test_controller_errors_are_not_hidden(code, exception):
    with pytest.raises(exception):
        query([("71{}23\r".format(code)).encode("ascii")])


def test_oversized_frame_tail_is_not_accepted_as_a_position():
    assert query([b"x" * 4097, b"71023 999\r", b"71023 123\r"]) == 123


def test_oversized_complete_frame_is_discarded():
    assert query([b"x" * 4097 + b"\r71023 123\r"]) == 123


def test_unformatted_acknowledgement_still_works():
    assert query([b"71022\r"], command="71022 100", output_format=None) == ""


def legacy_query(chunks, commands, formats=None, wait=True):
    from leica_microscope.includes.comport import send_command_and_wait
    ser = FragmentedSerial(chunks)
    with patch("leica_microscope.includes.comport.Connection") as connection, \
            patch("leica_microscope.includes.comport.time.perf_counter", side_effect=lambda: ser.clock):
        connection.return_value.__enter__.return_value = ser
        result = send_command_and_wait(commands, "SIMULATED", formats, wait=wait)
    return result, ser.writes


def test_legacy_batch_handles_fragments_noise_duplicates_and_out_of_order_replies():
    commands = ("72023", "73023", "71023")
    result, writes = legacy_query([b"7", b"\r73023 20\r73023 20\r71023 12",
                                  b"345\r72023 10\r"], commands, [int, int, int])
    assert result == [10, 20, 12345]
    assert writes == [c + "\r" for c in commands]


def test_legacy_incomplete_batch_reports_missing_command():
    with pytest.raises(TimeoutError, match="73023"):
        legacy_query([b"72023 10\r72023 10\r"], ["72023", "73023"], [int, int])


def test_legacy_objective_queries_match_property_without_short_line_crash():
    result, _ = legacy_query([b"76033\r76033 2 2 0.4\r76033 2 1 20\r"],
                             ["76033 a 1", "76033 a 2"],
                             [[None, None, int], [None, None, float]])
    assert result == [20, 0.4]


def test_legacy_motion_is_not_resent_on_timeout():
    from leica_microscope.includes.comport import send_command_and_wait
    ser = FragmentedSerial([])
    with patch("leica_microscope.includes.comport.Connection") as connection, \
            patch("leica_microscope.includes.comport.time.perf_counter", side_effect=lambda: ser.clock):
        connection.return_value.__enter__.return_value = ser
        with pytest.raises(TimeoutError):
            send_command_and_wait("71022 100", "SIMULATED")
    assert ser.writes == ["71022 100\r"]


def test_legacy_no_wait_and_controller_error_preserved():
    assert legacy_query([], "71022 100", wait=False) == (None, ["71022 100\r"])
    with pytest.raises(FlowError):
        legacy_query([b"71322\r"], "71022 100")
