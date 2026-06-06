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
from PySide6.QtGui import QColor, QDrag, QFont, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

