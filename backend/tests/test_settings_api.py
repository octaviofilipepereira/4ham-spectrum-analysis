from app.api import settings as settings_api


def _make_usb_device(
    root,
    name,
    *,
    vendor_id="0bda",
    product_id="2838",
    manufacturer="RTLSDRBlog",
    product="Blog V4",
    busnum="1",
    devnum="8",
):
    device_dir = root / name
    device_dir.mkdir(parents=True, exist_ok=True)
    (device_dir / "idVendor").write_text(f"{vendor_id}\n", encoding="utf-8")
    (device_dir / "idProduct").write_text(f"{product_id}\n", encoding="utf-8")
    (device_dir / "manufacturer").write_text(f"{manufacturer}\n", encoding="utf-8")
    (device_dir / "product").write_text(f"{product}\n", encoding="utf-8")
    (device_dir / "busnum").write_text(f"{busnum}\n", encoding="utf-8")
    (device_dir / "devnum").write_text(f"{devnum}\n", encoding="utf-8")
    return device_dir


def test_build_rtl_recovery_info_detects_rtl_usbreset_command(monkeypatch, tmp_path):
    _make_usb_device(tmp_path, "1-4")
    monkeypatch.setattr(settings_api, "_SYS_USB_ROOT", tmp_path)
    monkeypatch.setattr(settings_api, "command_exists", lambda name: name == "usbreset")

    info = settings_api._build_rtl_recovery_info()

    assert info["detected"] is True
    assert info["usbreset_installed"] is True
    assert info["bus_device"] == "001/008"
    assert info["device_path"] == "/dev/bus/usb/001/008"
    assert info["usbreset_command"] == "sudo usbreset 001/008"
    assert info["usbreset_vid_pid_command"] == "sudo usbreset 0bda:2838"
    assert info["product"] == "Blog V4"


def test_build_rtl_recovery_info_handles_missing_rtl(monkeypatch, tmp_path):
    _make_usb_device(
        tmp_path,
        "1-1",
        vendor_id="05e3",
        product_id="0610",
        manufacturer="GenesysLogic",
        product="USB2.0 Hub",
        busnum="1",
        devnum="5",
    )
    monkeypatch.setattr(settings_api, "_SYS_USB_ROOT", tmp_path)
    monkeypatch.setattr(settings_api, "command_exists", lambda name: False)

    info = settings_api._build_rtl_recovery_info()

    assert info == {
        "detected": False,
        "usbreset_installed": False,
    }