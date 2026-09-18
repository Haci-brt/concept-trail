"""Lightweight markdown syntax highlighting for the note editor."""
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._rules = []

        header_fmt = QTextCharFormat()
        header_fmt.setForeground(QColor("#895cf5"))
        header_fmt.setFontWeight(QFont.Weight.Bold)
        self._rules.append((QRegularExpression(r"^#{1,6}\s.*$"), header_fmt))

        bold_fmt = QTextCharFormat()
        bold_fmt.setFontWeight(QFont.Weight.Bold)
        bold_fmt.setForeground(QColor("#f0f0f0"))
        self._rules.append((QRegularExpression(r"\*\*(?!\s)([^*]+?)(?<!\s)\*\*"), bold_fmt))

        italic_fmt = QTextCharFormat()
        italic_fmt.setFontItalic(True)
        italic_fmt.setForeground(QColor("#d0d0d0"))
        self._rules.append((QRegularExpression(r"(?<!\*)\*(?!\s)([^*]+?)(?<!\s)\*(?!\*)"), italic_fmt))

        list_fmt = QTextCharFormat()
        list_fmt.setForeground(QColor("#e0a03f"))
        self._rules.append((QRegularExpression(r"^\s*[-*+]\s"), list_fmt))
        self._rules.append((QRegularExpression(r"^\s*\d+\.\s"), list_fmt))

        code_fmt = QTextCharFormat()
        code_fmt.setForeground(QColor("#7fd88f"))
        code_fmt.setFontFamily("Consolas")
        self._rules.append((QRegularExpression(r"`[^`]+`"), code_fmt))

        link_fmt = QTextCharFormat()
        link_fmt.setForeground(QColor("#c58fff"))
        self._rules.append((QRegularExpression(r"\[[^\]]*\]\([^)]*\)"), link_fmt))

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
