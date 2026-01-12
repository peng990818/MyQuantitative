import feedparser
from datetime import datetime
import time
from utils.logger import logger


class RSSNewsLoader:
    def __init__(self):
        # 顶级加密货币媒体 RSS 源列表
        self.rss_sources = [
            "https://www.coindesk.com/arc/outboundfeeds/rss/",  # CoinDesk (权威)
            "https://cointelegraph.com/rss",  # Cointelegraph (量大)
            "https://theblock.co/rss",  # The Block (深度)
            "https://decrypt.co/feed"  # Decrypt (即时)
        ]

    def get_latest_news(self, limit=10):
        """
        聚合多个 RSS 源，按时间排序，返回最新的 N 条
        """
        all_news = []

        for url in self.rss_sources:
            try:
                feed = feedparser.parse(url)
                if not feed.entries:
                    continue

                for entry in feed.entries[:5]:  # 每个源只取最新的 5 条，减少处理量
                    # 获取发布时间 (处理不同 RSS 的时间格式)
                    published_time = entry.get('published_parsed', time.gmtime())
                    timestamp = time.mktime(published_time)

                    # 组合数据
                    source_name = self._extract_source_name(url)
                    title = entry.title

                    all_news.append({
                        "timestamp": timestamp,
                        "text": f"[{source_name}] {title}",
                        "link": entry.link
                    })
            except Exception as e:
                logger.error(f"❌ RSS 读取失败 {url}: {e}")
                continue

        # 1. 按时间倒序排列 (最新的在前)
        all_news.sort(key=lambda x: x['timestamp'], reverse=True)

        # 2. 截取前 N 条
        final_list = [item['text'] for item in all_news[:limit]]

        logger.info(f"📡 从 RSS 聚合了 {len(final_list)} 条最新新闻")
        return final_list

    def _extract_source_name(self, url):
        if "coindesk" in url: return "CoinDesk"
        if "cointelegraph" in url: return "CoinTelegraph"
        if "theblock" in url: return "TheBlock"
        if "decrypt" in url: return "Decrypt"
        return "News"


if __name__ == "__main__":
    loader = RSSNewsLoader()
    news = loader.get_latest_news()
    print("\n🌍 最新 RSS 聚合新闻:")
    for n in news:
        print(n)