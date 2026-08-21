"""Connection dialog: PuTTY-style saved sessions on the left, settings right."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..profiles import Profile, ProfileStore
from ..transport.serialport import BAUD_RATES, PARITY, list_ports


class SSHPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = QLineEdit()
        self.host.setPlaceholderText("hostname or IP")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(22)
        self.username = QLineEdit()
        self.auth = QComboBox()
        self.auth.addItem("Password", "password")
        self.auth.addItem("Private key file", "key")
        self.auth.addItem("SSH agent / default keys", "agent")

        self.key_file = QLineEdit()
        self.key_file.setPlaceholderText("~/.ssh/id_ed25519")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.key_file, 1)
        key_row.addWidget(browse)
        key_widget = QWidget()
        key_widget.setLayout(key_row)

        form = QFormLayout(self)
        form.addRow("Host", self.host)
        form.addRow("Port", self.port)
        form.addRow("Username", self.username)
        form.addRow("Authentication", self.auth)
        form.addRow("Key file", key_widget)

        self.auth.currentIndexChanged.connect(self._sync)
        self._key_widget = key_widget
        self._sync()

    def _sync(self):
        self._key_widget.setEnabled(self.auth.currentData() == "key")

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select private key")
        if path:
            self.key_file.setText(path)

    def load(self, p: Profile):
        self.host.setText(p.host)
        self.port.setValue(p.port or 22)
        self.username.setText(p.username)
        index = self.auth.findData(p.auth)
        self.auth.setCurrentIndex(max(index, 0))
        self.key_file.setText(p.key_file)

    def apply(self, p: Profile):
        p.kind = "ssh"
        p.host = self.host.text().strip()
        p.port = self.port.value()
        p.username = self.username.text().strip()
        p.auth = self.auth.currentData()
        p.key_file = self.key_file.text().strip()

    def validate(self) -> str:
        if not self.host.text().strip():
            return "Enter a host to connect to."
        return ""


class SerialPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.device = QComboBox()
        self.device.setEditable(True)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_ports)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.device, 1)
        row.addWidget(refresh)
        device_widget = QWidget()
        device_widget.setLayout(row)

        self.baud = QComboBox()
        self.baud.setEditable(True)
        for rate in BAUD_RATES:
            self.baud.addItem(str(rate))
        self.baud.setCurrentText("9600")

        self.bytesize = QComboBox()
        for n in (5, 6, 7, 8):
            self.bytesize.addItem(str(n), n)
        self.bytesize.setCurrentText("8")

        self.parity = QComboBox()
        for name in PARITY:
            self.parity.addItem(name, name)

        self.stopbits = QComboBox()
        for value, text in ((1, "1"), (1.5, "1.5"), (2, "2")):
            self.stopbits.addItem(text, value)

        self.rtscts = QCheckBox("RTS/CTS hardware flow control")
        self.xonxoff = QCheckBox("XON/XOFF software flow control")

        form = QFormLayout(self)
        form.addRow("Port", device_widget)
        form.addRow("Speed", self.baud)
        form.addRow("Data bits", self.bytesize)
        form.addRow("Parity", self.parity)
        form.addRow("Stop bits", self.stopbits)
        form.addRow("", self.rtscts)
        form.addRow("", self.xonxoff)

        hint = QLabel("Cisco console default is 9600-8-N-1, no flow control.")
        hint.setStyleSheet("color: gray;")
        form.addRow("", hint)

        self.refresh_ports()

    def refresh_ports(self):
        current = self.device.currentText()
        self.device.clear()
        for device, description in list_ports():
            label = device if description == device else f"{device} — {description}"
            self.device.addItem(label, device)
        if current:
            self.device.setCurrentText(current)

    def _selected_device(self) -> str:
        data = self.device.currentData()
        if data:
            return data
        return self.device.currentText().split(" — ")[0].strip()

    def load(self, p: Profile):
        if p.device:
            index = self.device.findData(p.device)
            if index >= 0:
                self.device.setCurrentIndex(index)
            else:
                self.device.setCurrentText(p.device)
        self.baud.setCurrentText(str(p.baud))
        self.bytesize.setCurrentText(str(p.bytesize))
        self.parity.setCurrentText(p.parity)
        index = self.stopbits.findData(p.stopbits)
        self.stopbits.setCurrentIndex(max(index, 0))
        self.rtscts.setChecked(p.rtscts)
        self.xonxoff.setChecked(p.xonxoff)

    def apply(self, p: Profile):
        p.kind = "serial"
        p.device = self._selected_device()
        try:
            p.baud = int(self.baud.currentText())
        except ValueError:
            p.baud = 9600
        p.bytesize = self.bytesize.currentData()
        p.parity = self.parity.currentData()
        p.stopbits = self.stopbits.currentData()
        p.rtscts = self.rtscts.isChecked()
        p.xonxoff = self.xonxoff.isChecked()

    def validate(self) -> str:
        if not self._selected_device():
            return "Select a serial port."
        return ""


class TerminalPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scrollback = QSpinBox()
        self.scrollback.setRange(0, 200000)
        self.scrollback.setSingleStep(1000)
        self.scrollback.setValue(5000)

        self.font_family = QLineEdit()
        self.font_family.setPlaceholderText("(system monospace)")
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 48)
        self.font_size.setValue(11)

        self.log_path = QLineEdit()
        self.log_path.setPlaceholderText("(no session logging)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.log_path, 1)
        row.addWidget(browse)
        log_widget = QWidget()
        log_widget.setLayout(row)

        form = QFormLayout(self)
        form.addRow("Scrollback lines", self.scrollback)
        form.addRow("Font family", self.font_family)
        form.addRow("Font size", self.font_size)
        form.addRow("Log session to", log_widget)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Session log file")
        if path:
            self.log_path.setText(path)

    def load(self, p: Profile):
        self.scrollback.setValue(p.scrollback)
        self.font_family.setText(p.font_family)
        self.font_size.setValue(p.font_size)
        self.log_path.setText(p.log_path)

    def apply(self, p: Profile):
        p.scrollback = self.scrollback.value()
        p.font_family = self.font_family.text().strip()
        p.font_size = self.font_size.value()
        p.log_path = self.log_path.text().strip()


class ConnectDialog(QDialog):
    """Returns a Profile via .result_profile once accepted."""

    def __init__(self, store: ProfileStore, profile: Profile | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("New session")
        self.resize(720, 460)
        self.store = store
        self.result_profile: Profile | None = None

        # Left: saved sessions
        self.saved = QListWidget()
        self.saved.addItems(store.names())
        self.saved.itemDoubleClicked.connect(self._load_and_accept)
        self.saved.currentTextChanged.connect(self._load_selected)

        load_btn = QPushButton("Load")
        save_btn = QPushButton("Save…")
        del_btn = QPushButton("Delete")
        load_btn.clicked.connect(self._load_selected_clicked)
        save_btn.clicked.connect(self._save)
        del_btn.clicked.connect(self._delete)

        left = QVBoxLayout()
        left.addWidget(QLabel("Saved sessions"))
        left.addWidget(self.saved, 1)
        for button in (load_btn, save_btn, del_btn):
            left.addWidget(button)

        left_box = QGroupBox()
        left_box.setLayout(left)
        left_box.setFixedWidth(220)

        # Right: connection settings
        self.kind = QComboBox()
        self.kind.addItem("SSH", "ssh")
        self.kind.addItem("Serial", "serial")
        self.kind.currentIndexChanged.connect(self._sync_kind)

        self.ssh_page = SSHPage()
        self.serial_page = SerialPage()
        self.term_page = TerminalPage()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.ssh_page, "SSH")
        self.tabs.addTab(self.serial_page, "Serial")
        self.tabs.addTab(self.term_page, "Terminal")

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("Connection type"))
        kind_row.addWidget(self.kind)
        kind_row.addStretch(1)

        right = QVBoxLayout()
        right.addLayout(kind_row)
        right.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Open).setText("Connect")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)

        outer = QHBoxLayout(self)
        outer.addWidget(left_box)
        outer.addLayout(right, 1)

        self._apply_profile(profile or Profile())

    # -- profile <-> widgets ----------------------------------------------

    def _apply_profile(self, p: Profile):
        index = self.kind.findData(p.kind)
        self.kind.setCurrentIndex(max(index, 0))
        self.ssh_page.load(p)
        self.serial_page.load(p)
        self.term_page.load(p)
        self._current_name = p.name
        self._sync_kind()

    def _collect(self) -> Profile:
        p = Profile(name=self._current_name)
        kind = self.kind.currentData()
        # Apply both pages so switching type doesn't lose the other's settings.
        self.ssh_page.apply(p)
        self.serial_page.apply(p)
        self.term_page.apply(p)
        p.kind = kind
        return p

    def _sync_kind(self):
        kind = self.kind.currentData()
        self.tabs.setCurrentIndex(0 if kind == "ssh" else 1)
        self.tabs.setTabEnabled(0, kind == "ssh")
        self.tabs.setTabEnabled(1, kind == "serial")

    # -- saved list --------------------------------------------------------

    def _load_selected(self, name: str):
        pass  # single click only highlights; Load/double-click commits

    def _load_selected_clicked(self):
        item = self.saved.currentItem()
        if item is None:
            return
        profile = self.store.get(item.text())
        if profile is not None:
            self._apply_profile(profile)

    def _load_and_accept(self, item):
        profile = self.store.get(item.text())
        if profile is not None:
            self._apply_profile(profile)
            self._accept()

    def _save(self):
        profile = self._collect()
        name, ok = QInputDialog.getText(self, "Save session", "Name:",
                                        text=profile.name)
        if not ok or not name.strip():
            return
        profile.name = name.strip()
        self._current_name = profile.name
        self.store.put(profile)
        self.saved.clear()
        self.saved.addItems(self.store.names())

    def _delete(self):
        item = self.saved.currentItem()
        if item is None:
            return
        if QMessageBox.question(self, "Delete session",
                                f"Delete “{item.text()}”?") != QMessageBox.Yes:
            return
        self.store.remove(item.text())
        self.saved.clear()
        self.saved.addItems(self.store.names())

    # -- accept ------------------------------------------------------------

    def _accept(self):
        page = self.ssh_page if self.kind.currentData() == "ssh" else self.serial_page
        error = page.validate()
        if error:
            QMessageBox.warning(self, "Incomplete", error)
            return
        profile = self._collect()
        if profile.name in ("", "New session"):
            profile.name = (profile.host or profile.device or "session")
        self.result_profile = profile
        self.accept()


def prompt_secret(parent, title: str, label: str) -> tuple[str, bool]:
    text, ok = QInputDialog.getText(parent, title, label, QLineEdit.Password)
    return text, ok


def confirm_host_key(parent, hostname: str, key) -> bool:
    fingerprint = key.get_fingerprint().hex(":")
    return QMessageBox.question(
        parent,
        "Unknown host key",
        f"The server at {hostname} presented a host key that is not in "
        f"known_hosts.\n\n"
        f"Type: {key.get_name()}\n"
        f"Fingerprint: {fingerprint}\n\n"
        f"Only accept this if you can verify the fingerprint out of band. "
        f"Accept and remember it?",
    ) == QMessageBox.Yes
