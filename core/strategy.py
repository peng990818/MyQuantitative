from abc import ABC, abstractmethod
import pandas as pd

class BaseStrategy(ABC):
    def __init__(self, name="BaseStrategy"):
        self.name = name

    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        步骤1: 接收原始K线，计算该策略需要的指标 (EMA, RSI, ADX...)
        """
        pass

    @abstractmethod
    def check_signal(self, row: pd.Series) -> dict:
        """
        步骤2: 接收单根K线(包含指标)，返回交易信号
        Return: {'action': 'BUY'/'SELL'/None, 'atr': float}
        """
        pass