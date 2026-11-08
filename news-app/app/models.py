"""ORM 模型：源站点、新闻、标签、抓取日志。"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    region_province: Mapped[str] = mapped_column(String(20), default="广东省")
    region_city: Mapped[str] = mapped_column(String(20), default="")
    region_district: Mapped[str] = mapped_column(String(20), default="")  # 区/县，市级源为空
    level: Mapped[str] = mapped_column(String(20), default="city")  # province|city|district
    base_url: Mapped[str] = mapped_column(String(500), default="")
    list_url: Mapped[str] = mapped_column(String(500))
    fetch_type: Mapped[str] = mapped_column(String(10), default="html")  # rss|html
    selector_config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    news: Mapped[list["News"]] = relationship(back_populates="source")


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    content_text: Mapped[str] = mapped_column(Text, default="")
    content_html: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000))
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    title_hash: Mapped[str] = mapped_column(String(64), index=True)
    simhash: Mapped[int] = mapped_column(Integer, default=0)  # sqlite 下存指纹低 64 位有符号整数
    simhash_hex: Mapped[str] = mapped_column(String(16), default="")  # 便于跨库一致比较

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    source: Mapped["Source"] = relationship(back_populates="news")

    region_province: Mapped[str] = mapped_column(String(20), default="广东省")
    region_city: Mapped[str] = mapped_column(String(20), default="")
    region_district: Mapped[str] = mapped_column(String(20), default="")
    level: Mapped[str] = mapped_column(String(20), default="city")

    content_type: Mapped[str] = mapped_column(String(20), default="news")
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetch_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    status: Mapped[str] = mapped_column(String(20), default="fetched")  # fetched|interpreted|skipped|failed
    review_status: Mapped[str] = mapped_column(String(20), default="auto")  # auto|pending|reviewed
    version: Mapped[int] = mapped_column(Integer, default=1)

    ai_summary: Mapped[str] = mapped_column(Text, default="")
    ai_key_points: Mapped[list] = mapped_column(JSON, default=list)
    ai_analysis: Mapped[str] = mapped_column(Text, default="")
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ai_model: Mapped[str] = mapped_column(String(50), default="")
    ai_error: Mapped[str] = mapped_column(Text, default="")
    interpreted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tags: Mapped[list["Tag"]] = relationship(secondary="news_tags", lazy="selectin")

    __table_args__ = (
        Index("ix_news_publish", "publish_time"),
        Index("ix_news_city", "region_city"),
        Index("ix_news_status", "status"),
    )


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    category: Mapped[str] = mapped_column(String(20), default="theme")  # theme|custom


class NewsTag(Base):
    __tablename__ = "news_tags"
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class SkippedURL(Base):
    """已确认无有效正文的条目，短期内抑制重复下载。

    政府站列表里常有纯图片海报页、视频页或已下线的失效链接，正文提取为空。
    这类条目不入库（避免污染新闻流），但下轮仍会被当成新条目重新下载，
    每轮制造一条无意义失败备注。记录后按 TTL 静默跳过，到期自动重试。
    """

    __tablename__ = "skipped_urls"

    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    reason: Mapped[str] = mapped_column(String(20), default="empty")  # empty|not_found
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class FetchLog(Base):
    __tablename__ = "fetch_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|error
    found: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    duplicated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
