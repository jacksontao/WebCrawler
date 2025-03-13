# Dp_Click

自动化翻页，滚动获取链接

## 依赖

- Python 3.x
- `DrissionPage`
- `loguru`
- `concurrent.futures`

## 安装

请确保安装了所需的库，可以使用以下命令安装：

```bash
pip install drissionpage loguru

函数说明
parse_item(url): 处理提取到的文章链接，调用 get_article(url) 获取文章内容并打印。

DP_click(url, head, text=None, mode=None, xpath=None, pages=None, port=18080):

url: 要爬取的网页链接。
head: 是否使用有头模式（非无头模式）。
text: 点击加载更多或下一页的按钮文本。
mode: 滚动模式（scroll 或 next_page）。
xpath: 用于提取链接的 XPath 表达式。
pages: 在 next_page 模式下要点击的页数。
port: 代理端口（可选）。

if __name__ == '__main__':
    DP_click(url='https://zhonghua.gmw.cn/news.htm?q=deepseek', head=True, text="下一页", mode="next_page", xpath='//h3/a/@href', pages=2)
