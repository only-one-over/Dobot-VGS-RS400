#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PySide6 compatibility exports used by the desktop UI."""

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QObject,
    Qt,
    QThread,
    QTimer,
    Signal as pyqtSignal,
    Slot as pyqtSlot,
    Property as pyqtProperty,
)
from PySide6.QtGui import QColor, QDrag, QFont, QImage, QPainter, QPalette, QPen, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
