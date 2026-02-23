import asyncio

import numpy as np

from app.decoders.ft_external import ExternalFtDecoder, parse_external_decoder_line, parse_wsprd_line


def test_parse_external_decoder_line_jsonl():
    line = '{"mode":"FT8","callsign":"CT7BFV","snr_db":-12.5,"frequency_hz":7075000,"msg":"CQ CT7BFV"}'
    event = parse_external_decoder_line(line=line, mode="FT8", output_format="jsonl")

    assert event is not None
    assert event["mode"] == "FT8"
    assert event["callsign"] == "CT7BFV"
    assert int(event["frequency_hz"]) == 7075000
    assert float(event["snr_db"]) == -12.5
    assert event["source"] == "internal_ft_external"


def test_parse_external_decoder_line_wsjt_style():
    line = "222100 -15 -0.0  508 ~  CQ EA7MJ IM66"
    event = parse_external_decoder_line(line=line, mode="FT8", frequency_hz=7075000, output_format="wsjt")

    assert event is not None
    assert event["mode"] == "FT8"
    assert event["callsign"] == "EA7MJ"
    # frequency_hz = dial (7075000) + df_hz (508)
    assert int(event["frequency_hz"]) == 7075508
    assert event["msg"].startswith("CQ")


def test_external_ft_decoder_emits_event_from_runner_output():
    async def scenario():
        emitted = []

        def on_event(payload):
            emitted.append(dict(payload))

        def iq_provider(num_samples):
            return (np.ones(int(num_samples), dtype=np.float32) + 1j * np.zeros(int(num_samples), dtype=np.float32))

        def command_runner(command, timeout_s=20.0):
            return {
                "returncode": 0,
                "stdout": '{"mode":"FT8","callsign":"CT7BFV","snr_db":-9,"msg":"CQ CT7BFV"}\n',
                "stderr": "",
            }

        decoder = ExternalFtDecoder(
            command_template="ft8-decoder --mode {mode} --input {wav_path}",
            output_format="jsonl",
            modes=["FT8"],
            window_seconds={"FT8": 0.2},
            poll_s=0.05,
            decode_timeout_s=2.0,
            iq_chunk_size=64,
            iq_provider=iq_provider,
            sample_rate_provider=lambda: 200,
            frequency_provider=lambda: 7075000,
            on_event=on_event,
            command_runner=command_runner,
        )

        started = await decoder.start()
        assert started is True
        await asyncio.sleep(0.35)
        await decoder.stop()

        status = decoder.snapshot()
        assert status["windows_processed"] >= 1
        assert status["events_emitted"] >= 1
        assert status["last_event_at"] is not None
        assert status["last_exit_code"] == 0
        assert len(emitted) >= 1
        assert emitted[0]["callsign"] == "CT7BFV"

    asyncio.run(scenario())


def test_external_ft_decoder_formats_mode_flag_placeholder():
    async def scenario():
        commands = []

        def iq_provider(num_samples):
            return (np.ones(int(num_samples), dtype=np.float32) + 1j * np.zeros(int(num_samples), dtype=np.float32))

        def command_runner(command, timeout_s=20.0):
            commands.append(str(command))
            return {"returncode": 0, "stdout": "", "stderr": ""}

        decoder = ExternalFtDecoder(
            command_template="decoder {mode_flag} {wav_path}",
            output_format="wsjt",
            modes=["FT4"],
            window_seconds={"FT4": 0.2},
            poll_s=0.05,
            decode_timeout_s=2.0,
            iq_chunk_size=64,
            iq_provider=iq_provider,
            sample_rate_provider=lambda: 200,
            frequency_provider=lambda: 7075000,
            on_event=None,
            command_runner=command_runner,
        )

        await decoder.start()
        await asyncio.sleep(0.25)
        await decoder.stop()

        assert len(commands) >= 1
        assert "--ft4" in commands[0]

    asyncio.run(scenario())


def test_parse_wsprd_line_standard():
    """Parse a typical wsprd stdout line."""
    line = "2502 2220  -22   0.3   7038682   0  CT1FRF IO50  37"
    event = parse_wsprd_line(line, frequency_hz=7038600)

    assert event is not None
    assert event["mode"] == "WSPR"
    assert event["callsign"] == "CT1FRF"
    assert int(event["frequency_hz"]) == 7038682
    assert float(event["snr_db"]) == -22.0
    assert float(event["dt_s"]) == 0.3
    assert event["grid"] == "IO50"
    assert event["power_dbm"] == 37
    assert event["source"] == "internal_ft_external"


def test_parse_wsprd_line_minimal_grid():
    """wsprd may emit lines with grid but no power."""
    line = "2502 2230   -8   0.1   14097100   1  N0CALL FN31"
    event = parse_wsprd_line(line)

    assert event is not None
    assert event["callsign"] == "N0CALL"
    assert event["mode"] == "WSPR"
    assert int(event["frequency_hz"]) == 14097100
    assert event["grid"] == "FN31"


def test_parse_wsprd_line_rejects_noise():
    """Garbage lines should return None."""
    assert parse_wsprd_line("") is None
    assert parse_wsprd_line("some random noise text") is None
    assert parse_wsprd_line("<DecsacokFrequency>  7038600") is None


def test_external_ft_decoder_wspr_command_template():
    """WSPR mode should use the per-mode command_templates override."""
    async def scenario():
        commands = []

        def iq_provider(num_samples):
            return (np.ones(int(num_samples), dtype=np.float32)
                    + 1j * np.zeros(int(num_samples), dtype=np.float32))

        def command_runner(command, timeout_s=20.0):
            commands.append(str(command))
            return {
                "returncode": 0,
                "stdout": "2502 2220  -15   0.2   7038700   0  EA4GPZ IN80  30\n",
                "stderr": "",
            }

        decoder = ExternalFtDecoder(
            command_template="jt9 {mode_flag} -p {period_int} -d 3 {wav_path}",
            output_format="wsjt",
            command_templates={"WSPR": "wsprd -f {frequency_mhz} -d -w {wav_path}"},
            output_formats={"WSPR": "wsprd"},
            modes=["WSPR"],
            window_seconds={"WSPR": 0.2},
            poll_s=0.05,
            decode_timeout_s=2.0,
            iq_chunk_size=64,
            iq_provider=iq_provider,
            sample_rate_provider=lambda: 200,
            frequency_provider=lambda: 7038600,
            on_event=None,
            command_runner=command_runner,
        )

        await decoder.start()
        await asyncio.sleep(0.3)
        await decoder.stop()

        assert len(commands) >= 1
        assert "wsprd" in commands[0]
        assert "7.038600" in commands[0]

    asyncio.run(scenario())
