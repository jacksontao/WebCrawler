# 工具文档

## 概述
本工具提供了一套完整的网页爬取解决方案，支持内容页识别、分页处理、链接提取、内容抓取及URL过滤等功能。主要特点包括：
- 智能URL分类（内容页/列表页）
- 分页处理支持直接解析和二分查找两种模式
- 基于XPath和正则表达式的链接提取
- 内容提取与清洗
- 布隆过滤器实现URL去重
- 自动重试机制和缓存支持

## 安装
```bash

pip install WebCrawler-x==4.0

pip install requests beautifulsoup4 loguru fake-useragent pybloom-live retrying gne htmldate lxml lxparse json_repair
```

## 1.使用

### 1.1.内容页和详情页的区分

| 特征类型   | 内容页特征                 | 列表页特征                  |
|------------|--------------------------|---------------------------|
| **URL结构** | 包含.html/.php等扩展名     | 路径短且以/结尾            |
| **参数特征** | 包含数字ID参数            | 包含category/list等关键字  |
| **路径层级** | 层级深度≥3                | 层级深度≤2                 |
| **示例**    | `/news/123.html?id=456`   | `/news/list?page=1`        |

### 特征说明
- **URL结构**：内容页通常包含文件扩展名，列表页路径更简洁
- **参数特征**：内容页参数含数字ID，列表页参数含分类关键词
- **路径层级**：内容页路径层级更深（≥3级），列表页路径较浅
- 内容页和列表页识别

```python
def categorize_urls(urls, base_domain):
    """
    输入: 
        urls - 待分类URL列表
        base_domain - 基准域名
    
    输出: 
        (content_pages, list_pages) - 内容页/列表页元组
    """
```


### 1.2.分页处理


```python
all_links, total_pages = get_page_info(
    url="http://example.com/news?page=1",
    page_param="page", #页码参数名（如'page'或'/page/'）
    mode='direct',  #分页模式：'direct'直接解析 / 'binary'二分查找
    use_cache=True,  #是否使用缓存
    step=1,  #页码步长
    has_index=False,  #是否有索引
    custom_base_path=None,  #自定义最大页数基准路径
)
```


### 1.3. 列表页链接提取


```python
article_links = get_links(
    url="http://example.com/news",
    xpath="//div[@class='article']/a/@href", #链接提取XPath
    regex=r'\/news\/\d+\.html',  #链接提取正则表达式
    required_fields=['detail'] #筛选，内容页通常含有固定字段如 detail/news/content，
    html=None,  #HTML文本,如果页面是动态加载的，可以传入HTML文本
)
```


### 1.4. 内容页提取


```python
article_data = get_article(
    url="http://example.com/news/123.html",
    parsing_mode='lx', #解析模式：'lx'使用lxparse / gne GeneralNewsExtractor
    Filter=True,  #是否过滤,不重复提取，已经提取过的内容
)

返回字段
{
  "_id": "md5哈希值",
  "url": "文章URL",
  "title": "文章标题",
  "content": "清洗后的正文内容",
  "publish_time": "发布日期",
  "updateTime": "抓取时间"
}
```


### 1.5. 完整示例


```python
# 初始化过滤器
url_filter = URLFilter()

# 获取分页
all_pages, total = get_page_info(
    "http://example.com/news?page=1",
    page_param="page",
    use_cache=True
)

# 遍历分页
for page in all_pages:
    # 提取内容页链接
    links = get_links(page, xpath="//a[@class='title']/@href")
    
    # 分类处理
    content_links, _ = categorize_urls(links, "example.com")
    
    for link in content_links:
            article = get_article(link, parsing_mode='lx', Filter=True)
            if article:
                save_to_database(article)
```
