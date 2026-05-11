# WebCrawler_x

`WebCrawler_x` 是一个面向实战的网页采集工具库，支持：

- 列表分页发现与分页链接生成
- 列表链接提取（XPath / 自动）
- 文章正文提取（lx / gne / xpath）
- 滚动页抓取（含自动模式切换）
- 多线程批量执行
- URL 去重（BloomFilter）
- 基础内容有效性校验

---

## 目录

- [功能概览](#功能概览)
- [安装与环境](#安装与环境)
- [快速开始](#快速开始)
- [核心模式说明](#核心模式说明)
- [API 参考](#api-参考)
  - [get_page_info](#1-get_page_info)
  - [get_links](#2-get_links)
  - [get_article](#3-get_article)
  - [get_scrolling_page](#4-get_scrolling_page)
  - [run_in_threads](#5-run_in_threads)
  - [search_links_stream](#6-search_links_stream)
- [WebCrawler 类](#webcrawler-类)
- [常见用法模板](#常见用法模板)
- [常见问题](#常见问题)
- [注意事项](#注意事项)

---

## 功能概览

### 1) 分页处理
- 支持 `direct / binary / auto` 分页策略
- 支持 query 参数分页（如 `?page=2`）和路径分页（如 `/pg2/`）
- 在找不到“尾页”文本时，支持从分页 `a[href]` 中提取最大页码（兼容如 gitee 列表页）

### 2) 智能请求模式
几乎所有核心请求函数支持：

- `mode='s'`：纯 `requests`
- `mode='d'`：`DrissionPage/WebPage` 浏览器渲染
- `mode='auto'`：智能切换
  - 简单静态页优先 `s`
  - 403 / 验证页 / 重 JS 页面自动切 `d`
  - `d` 返回空 HTML 时自动回退 `s`

### 3) 解析能力
- 列表页：`LxParse.parse_list` 或 XPath
- 详情页：
  - `parsing_mode='lx'`
  - `parsing_mode='gne'`
  - `parsing_mode='xpath'`

### 4) 滚动页
- 新增 `get_scrolling_page()`
- 支持滚动多轮抓取、过滤、自动模式回退

---

## 安装与环境

## 安装

```bash
pip install WebCrawler_x
```

或本地开发安装：

```bash
pip install -e .
```

## 依赖说明
主要依赖：

- `requests`
- `DrissionPage`
- `lxml`
- `bs4`
- `gne`
- `lxparse`
- `retrying`
- `fake_useragent`
- `pybloom_live`

---

## 快速开始

```python
from WebCrawler_x import get_page_info, get_links, get_article

start_url = 'https://gitee.com/explore/all?page=1'

# 1) 拿分页链接
pages, total = get_page_info(
    start_url,
    page_param='page',
    mode='auto',
    page_mode='direct'
)
print('total=', total)

# 2) 抓某页列表链接
links = get_links(
    pages[0],
    xpath='//a/@href',
    base_url='https://gitee.com',
    mode='auto'
)
print('links=', len(links))

# 3) 抓一篇详情
if links:
    article = get_article(links[0], mode='auto', parsing_mode='lx')
    print(article.get('title') if article else None)
```

---

## 核心模式说明

## 请求模式 `mode`

- `s`：只用 `requests`
- `d`：只用浏览器渲染
- `auto`：智能策略

推荐：
- 一般新闻站、静态站先 `auto`
- 明确重 JS 的站点直接 `d`
- 高并发批采场景优先 `s`

## 分页策略 `page_mode`（仅 `get_page_info`）

- `direct`：通过尾页/分页链接直接推导总页数
- `binary`：通过“页是否存在”二分逼近最大页
- `auto`：先 direct，失败再 binary

---

## API 参考

### 1) `get_page_info`

```python
get_page_info(
    url,
    page_param=None,
    step=1,
    first_num=1,
    mode='auto',
    max_attempts=10,
    use_cache=False,
    cache_file=None,
    proxy=None,
    stop_max_attempt_number=3,
    sleep=1,
    has_index=False,
    custom_base_path=None,
    use_drission=False,
    drission_sleep=2,
    page_mode='auto'
)
```

返回：`(all_pages_link: List[str], total_pages: int)`

要点：
- `page_mode='direct'` 下找不到“尾页”时，会扫描 `a[href*='page=']` 提取最大页码
- 可配合 `use_cache=True` 缓存分页结果

---

### 2) `get_links`

```python
get_links(
    url,
    xpath='',
    proxy=None,
    article_nums=None,
    required_fields=None,
    base_url=None,
    regex=None,
    html=None,
    use_drission=False,
    sleep=0,
    mode='auto'
)
```

返回：`List[str]`

要点：
- `xpath` 为空时走自动列表提取
- `required_fields` 和 `regex` 可二次过滤
- 支持传入 `html` 跳过请求

---

### 3) `get_article`

```python
get_article(
    url,
    proxy=None,
    parsing_mode='lx',
    headers=headers,
    Filter=False,
    url_filter=None,
    use_drission=False,
    xpath_item=None,
    sleep=0,
    cookies=None,
    html=None,
    mode='auto'
)
```

返回：`dict | None`

字段示例：
- `title`
- `content`
- `author`
- `publish_time`
- `url`
- `_id`
- `updateTime`
- `addDateTime`

---

### 4) `get_scrolling_page`

```python
get_scrolling_page(
    url,
    row_xpath='//a/@href',
    max_scrolls=5,
    wait=1.0,
    proxy=None,
    base_url=None,
    required_fields=None,
    regex=None,
    mode='auto',
    use_drission=False
)
```

返回：`List[str]`

要点：
- `mode='s'`：退化为单页解析
- `mode='d'`：浏览器滚动抓取
- `mode='auto'`：先判静态/验证，再决定 `s/d`

---

### 5) `run_in_threads`

```python
run_in_threads(
    func,
    datas,
    max_workers=10,
    rate_limit=None,
    retries=3,
    retry_delay=1,
    batch_size=None,
    batch_delay=0
)
```

返回：按输入顺序对应的结果列表。

适合：批量详情抓取、批量解析任务。

---

### 6) `search_links_stream`

```python
search_links_stream(
    start_url,
    pattern,
    max_depth=3,
    max_breadth=5,
    batch_size=50
)
```

返回：生成器，按批次 yield 链接列表。

---

## WebCrawler 类

库中提供 `WebCrawler` 封装类（包含分页、链接提取、文章提取等常用流程）。

典型使用：

```python
from WebCrawler_x import WebCrawler

crawler = WebCrawler(base_url='https://example.com', use_filter=True)
```

若你更偏函数式调用，可直接使用本文档的 API。

---



---

## 常见问题

### Q1: `get_scrolling_page` 导入不到？
请使用：

```python
from WebCrawler_x import get_scrolling_page
```

若仍失败，确认当前环境加载的是你刚修改过的 site-packages 路径。

### Q2: 为什么 `auto` 有时比 `s` 慢？
因为 `auto` 可能会尝试浏览器渲染。对明确静态站点请直接用 `mode='s'`。

### Q3: 分页总数识别不准怎么办？
优先传 `page_param`，必要时改用：

```python
page_mode='binary'
```

### Q4: 抓到很多无效内容？
可使用 `is_valid_data()` 做质量过滤，或强化 `required_fields/regex/xpath`。

---

## 注意事项

1. 请遵守目标站点 robots / 使用条款与法律法规。  
2. `d` 模式依赖本地浏览器运行环境，服务器环境需提前配置。  
3. 高并发时建议：
   - 控制 `max_workers`
   - 启用 `rate_limit`
   - 设置合理重试与超时
4. 若使用代理，建议统一在请求与浏览器两端同步配置。  

---

