# 工具文档


## 安装
```bash
pip install WebCrawler-x== 6.2
```

# WebCrawler - 实战级网页爬虫工具库



### ✨ 核心特性

1. **智能分页提取** - 自动检测分页参数，无需手动指定
2. **类封装** - 提供 `WebCrawler` 类，简化使用流程  
3. **完整文档** - 所有函数都有详细的文档字符串和使用示例
4. **类型提示** - 添加类型注解，提升代码可维护性
5. **兼容性** - 保持所有原有函数的使用方法不变

---

## 🚀 快速开始

### 1. 最简单的使用（自动分页）

```python
from WebCrawler_x import get_page_info

# 自动检测分页参数，无需指定 page_param
pages, total = get_page_info('https://example.com/news')
print(f"找到 {total} 页")
```

### 2. 使用 WebCrawler 类

```python
from WebCrawler_x import WebCrawler

# 初始化
crawler = WebCrawler('https://example.com')

# 自动分页
pages, total = crawler.get_pages('/news')

# 提取链接
links = crawler.extract_links(pages[0])

# 批量提取文章
articles = crawler.get_articles(links, max_workers=5)
```

### 3. 一键爬取整站

```python
crawler = WebCrawler('https://example.com')

# 自动完成：分页 -> 提取链接 -> 提取内容
all_articles = crawler.crawl_site('/news', max_pages=10)
```

---

## 📚 主要API

### 函数式 API

| 函数 | 说明 | 示例 |
|------|------|------|
| `get_page_info()` | 智能提取分页 | `pages, total = get_page_info(url)` |
| `get_links()` | 提取页面链接 | `links = get_links(url)` |
| `get_article()` | 提取文章内容 | `article = get_article(url)` |
| `run_in_threads()` | 多线程执行 | `results = run_in_threads(func, data)` |
| `search_links_stream()` | BFS搜索链接 | `for batch in search_links_stream(url, pattern):` |

### 类式 API（推荐）

```python
class WebCrawler:
    def __init__(base_url, proxy=None, use_filter=True)
    def get_pages(path, **kwargs) -> Tuple[List[str], int]
    def extract_links(url, **kwargs) -> List[str]
    def get_article(url, **kwargs) -> Dict
    def get_articles(urls, max_workers=5) -> List[Dict]
    def crawl_site(start_path, max_pages=None) -> List[Dict]
```

---

## 🎯 核心改进

### 1. 自动分页检测

**之前**：必须手动指定 `page_param`
```python
pages, total = get_page_info(url, page_param='page', mode='direct')
```

**现在**：自动检测，无需参数
```python
pages, total = get_page_info(url)  # mode='auto' 是默认值
```

**支持检测的分页类型**：
- URL参数型: `?page=1`, `?p=2`, `?pageNum=3`
- 路径型: `/page/1`, `/p/2`
- 文件名型: `_1.html`, `_2.html`

### 2. WebCrawler 类封装

提供统一的爬虫接口：

```python
crawler = WebCrawler('https://example.com')

# 所有方法都自动使用配置的 base_url 和 proxy
pages = crawler.get_pages('/news')
links = crawler.extract_links(pages[0])
articles = crawler.get_articles(links)
```

### 3. 完整的文档字符串

每个函数都包含：
- 功能描述
- 参数说明（类型 + 描述）
- 返回值说明
- 使用示例

```python
def get_page_info(url, page_param=None, ...):
    """
    智能获取分页信息，支持自动检测、直接解析和二分查找三种模式
    
    Args:
        url: 初始URL
        page_param: 页码参数名（可选，auto模式会自动检测）
        ...
    
    Returns:
        Tuple[List[str], int]: (页面链接列表, 总页数)
    
    Examples:
        >>> # 自动模式（推荐）
        >>> links, total = get_page_info('https://example.com/news')
    """
```

### 4. 类型提示

增加类型注解，提升代码可读性：

```python
from typing import List, Dict, Optional, Tuple

def get_links(url: str, xpath: str = '//a/@href', ...) -> List[str]:
    ...

def get_article(url: str, ...) -> Optional[Dict]:
    ...
```

---

## 📖 使用示例

查看 `examples.py` 获取更多示例：

- ✅ 示例1: 自动分页提取
- ✅ 示例2: 使用 WebCrawler 类
- ✅ 示例3: 一键爬取整站
- ✅ 示例4: 自定义 XPath
- ✅ 示例5: 使用代理
- ✅ 示例6: 提取特定链接
- ✅ 示例7: 渲染动态页面
- ✅ 示例8: URL去重
- ✅ 示例9: 分页模式对比
- ✅ 示例10: 批量爬取多站

---

## 🔧 高级功能

### 自定义 XPath 解析

```python
xpath_config = {
    'xpath_title': '//h1[@class="title"]/text()',
    'xpath_content': '//div[@class="content"]//text()',
    'xpath_author': '//span[@class="author"]/text()',
}

article = get_article(url, parsing_mode='xpath', xpath_item=xpath_config)
```

### 多线程批量爬取

```python
from WebCrawler import run_in_threads

def fetch_article(url):
    return get_article(url)

# 10个线程并发，自动限速和重试
results = run_in_threads(fetch_article, urls, max_workers=10, rate_limit=5)
```

### URL 去重

```python
from WebCrawler import URLFilter

# 创建过滤器
url_filter = URLFilter(capacity=1000000, file_path='seen_urls.pkl')

# 检查URL是否已爬取
if url_filter.is_url_new(url):
    article = get_article(url)
    url_filter.save(url)
```

---

## 🎨 设计原则

1. **向后兼容** - 所有原有函数调用方式保持不变
2. **渐进增强** - 提供类封装，但不强制使用
3. **智能默认** - 提供合理的默认参数，减少配置
4. **灵活扩展** - 支持自定义配置覆盖默认行为

---

## 📦 导出的 API

```python
from WebCrawler import (
    # 核心类
    WebCrawler,
    URLFilter,
    
    # 工具函数
    run_in_threads,
    get_page_info,
    get_links,
    get_article,
    search_links_stream,
    
    # 辅助函数
    is_content_page,
    categorize_urls,
    is_valid_data,
    create_low_memory_page,
)
```

---

## 💡 最佳实践

1. **优先使用类** - `WebCrawler` 类提供更简洁的API
2. **启用缓存** - 分页结果设置 `use_cache=True` 避免重复请求
3. **合理限速** - 使用 `rate_limit` 参数避免被封IP
4. **检查内容** - 使用 `is_valid_data()` 过滤无效内容
5. **错误处理** - 函数内置重试机制，无需手动处理

---

## 🔄 迁移指南

**从旧版本迁移非常简单，不需要修改任何代码！**

```python
# 旧代码仍然可以正常工作
pages, total = get_page_info(url, page_param='page', mode='direct')

# 但推荐使用新的简化方式
pages, total = get_page_info(url)  # 自动检测
```

---

## 📝 更新日志

### v2.0 (当前版本)

- ✨ 新增 `WebCrawler` 类封装
- ✨ 分页自动检测功能（mode='auto'）
- ✨ 完整的文档字符串和类型提示
- ✨ 新增 `crawl_site()` 一键爬取方法
- 🔧 优化日志输出，使用emoji提升可读性
- 📚 新增 10 个实战示例

### v1.0 (原版本)

- 基础爬虫功能
- 多线程支持
- URL去重


