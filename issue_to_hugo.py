import os
import argparse
import re
import requests
import json
import logging
from urllib.parse import unquote
from datetime import datetime
from github import Github, Auth
from bs4 import BeautifulSoup

CATEGORY_MAP = ["生活", "技术", "法律", "瞬间", "社会"]
PUBLISH_LABEL = "发布"

def setup_logger(debug=False):
    logger = logging.getLogger('issue-to-hugo')
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)
    
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger

def is_within_code_block(text, position):
    """检查指定位置是否在代码块内（``` 或 `）"""
    lines = text.split('\n')
    in_code_block = False
    in_inline_code = False
    char_count = 0
    
    for line in lines:
        line_start = char_count
        line_end = char_count + len(line) + 1  # 包括换行符
        
        if position >= line_start and position <= line_end:
            if in_inline_code:
                return True
            if in_code_block:
                return True
        
        # 检查多行代码块
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
        # 检查单行内联代码
        inline_code_matches = list(re.finditer(r'`[^`]+`', line))
        for match in inline_code_matches:
            start, end = match.span()
            if position >= line_start + start and position <= line_start + end:
                return True
        
        char_count += len(line) + 1
    
    return in_code_block

def extract_cover_image(body):
    """提取正文第一张图片（跳过代码块）作为封面图"""
    img_pattern = r"!\[([^\]]*?)\]\((https?:\/\/[^\)]+)\)"
    matches = list(re.finditer(img_pattern, body))
    
    for match in matches:
        img_url = match.group(2)
        start_pos = match.start()
        if not is_within_code_block(body, start_pos):
            body = body[:match.start()] + body[match.end():]
            return img_url, body
    return None, body

def safe_filename(filename):
    """生成安全的文件名，保留或推断文件扩展名"""
    clean_url = re.sub(r"\?.*$", "", filename)
    basename = os.path.basename(clean_url)
    decoded_name = unquote(basename)
    
    name, ext = os.path.splitext(decoded_name)
    safe_name = re.sub(r"[^a-zA-Z0-9\-_]", "_", name)
    if not ext.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        ext = ""
    if len(safe_name) > 100 - len(ext):
        safe_name = safe_name[:100 - len(ext)]
    
    return safe_name + ext

def download_image(url, output_path, token=None):
    """下载图片到指定路径，基于内容类型确定扩展名，并添加 GitHub 认证头"""
    try:
        headers = {}
        if token:
            headers['Authorization'] = f'token {token}'
        
        response = requests.get(url, stream=True, headers=headers)
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "").lower()
            ext = ".jpg"
            if "image/png" in content_type:
                ext = ".png"
            elif "image/jpeg" in content_type or "image/jpg" in content_type:
                ext = ".jpg"
            elif "image/gif" in content_type:
                ext = ".gif"
            elif "image/webp" in content_type:
                ext = ".webp"
            
            base, current_ext = os.path.splitext(output_path)
            if current_ext.lower() not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                output_path = base + ext
            else:
                output_path = base + current_ext
            
            with open(output_path, 'wb') as f:
                f.write(response.content)
            logging.info(f"图片下载成功: {url} -> {output_path}")
            return output_path
        else:
            logging.error(f"图片下载失败，状态码: {response.status_code}, URL: {url}")
    except Exception as e:
        logging.error(f"下载图片失败: {url} - {e}")
    return None

def replace_image_urls(body, issue_number, output_dir, token=None):
    """替换正文中的 Markdown 和 HTML 图片为本地图片，跳过代码块"""
    # Markdown 图片
    md_img_pattern = r"!\[([^\]]*?)\]\((https?:\/\/[^\)]+)\)"
    html_img_pattern = r'<img[^>]+src=["\']?(https?:\/\/[^"\'>]+)["\']?'
    
    def md_replacer(match):
        if is_within_code_block(body, match.start()):
            return match.group(0)
        alt_text = match.group(1)
        img_url = match.group(2)
        filename = f"{issue_number}_{safe_filename(img_url)}"
        output_path = os.path.join(output_dir, filename)
        final_path = download_image(img_url, output_path, token)
        if final_path:
            final_filename = os.path.basename(final_path)
            return f"![{alt_text}]({final_filename})"
        return match.group(0)
    
    def html_replacer(match):
        if is_within_code_block(body, match.start()):
            return match.group(0)
        img_url = match.group(1)
        alt_text = re.search(r'alt=["\']?([^"\'>]+)["\']?', match.group(0)) or ''
        alt_text = alt_text.group(1) if alt_text else 'Image'
        filename = f"{issue_number}_{safe_filename(img_url)}"
        output_path = os.path.join(output_dir, filename)
        final_path = download_image(img_url, output_path, token)
        if final_path:
            final_filename = os.path.basename(final_path)
            return f"![{alt_text}]({final_filename})"
        return match.group(0)
    
    body = re.sub(md_img_pattern, md_replacer, body, flags=re.IGNORECASE)
    body = re.sub(html_img_pattern, html_replacer, body, flags=re.IGNORECASE)
    return body

def sanitize_markdown(content):
    """清理Markdown中的不安全内容"""
    if not content:
        return ""
    
    soup = BeautifulSoup(content, "html.parser")
    allowed_tags = ["p", "a", "code", "pre", "blockquote", "ul", "ol", "li", "strong", "em", "img", "h1", "h2", "h3", "h4", "h5", "h6"]
    for tag in soup.find_all(True):
        if tag.name not in allowed_tags:
            tag.unwrap()
    
    return str(soup)

def extract_tags_from_body(body, logger):
    """从正文最后一行提取标签，跳过代码块"""
    if not body:
        logger.debug("Body is empty, no tags to extract")
        return [], body
    
    body = body.replace('\r\n', '\n').rstrip()
    lines = body.split('\n')
    if not lines:
        logger.debug("No lines in body, no tags to extract")
        return [], body
    
    last_line = lines[-1].strip()
    if is_within_code_block(body, len(body) - len(last_line)):
        logger.debug("Last line is within a code block, skipping tag extraction")
        return [], body
    
    logger.debug(f"Last line for tag extraction: '{last_line}'")
    tags = re.findall(r'\$(.+?)\$', last_line, re.UNICODE)
    tags = [tag.strip() for tag in tags if tag.strip()]
    
    if tags:
        logger.debug(f"Extracted tags: {tags}")
        body = '\n'.join(lines[:-1]).rstrip()
    else:
        logger.debug("No tags found in last line")
    
    return tags, body

def convert_issue(issue, output_dir, token, logger):
    """转换单个issue为Hugo内容"""
    try:
        labels = [label.name for label in issue.labels]
        if PUBLISH_LABEL not in labels or issue.state != "open":
            logger.debug(f"跳过 issue #{issue.number} - 未标记为发布")
            return False
        
        pub_date = issue.created_at.strftime("%Y%m%d")
        slug = f"{pub_date}_{issue.number}"
        post_dir = os.path.join(output_dir, slug)
        
        if os.path.exists(post_dir):
            logger.info(f"跳过 issue #{issue.number} - 目录 {post_dir} 已存在")
            return False
        
        os.makedirs(post_dir, exist_ok=True)
        
        body = issue.body or ""
        logger.debug(f"Raw issue body: '{body}'")
        cover_url, body = extract_cover_image(body)
        tags, body = extract_tags_from_body(body, logger)
        body = sanitize_markdown(body)
        body = replace_image_urls(body, issue.number, post_dir, token)
        logger.info(f"图片处理完成，{issue.number} 号 issue")
        
        categories = [tag for tag in labels if tag in CATEGORY_MAP]
        category = categories[0] if categories else "生活"
        
        cover_name = None
        if cover_url:
            try:
                cover_filename = f"cover_{safe_filename(cover_url)}"
                cover_path = os.path.join(post_dir, cover_filename)
                final_cover_path = download_image(cover_url, cover_path, token)
                if final_cover_path:
                    cover_name = os.path.basename(final_cover_path)
                    logger.info(f"封面图下载成功：{cover_url} > {cover_name}")
                else:
                    logger.error(f"封面图下载失败：{cover_url}")
            except Exception as e:
                logger.error(f"封面图下载失败：{cover_url} - {e}")
        
        title_escaped = issue.title.replace('"', '\\"')
        category_escaped = category.replace('"', '\\"')
        frontmatter_lines = [
            "---",
            f'title: "{title_escaped}"',
            f"date: \"{issue.created_at.strftime('%Y-%m-%d')}\"",
            f"slug: \"{slug}\"",
            f"categories: [\"{category_escaped}\"]",
            f"tags: {json.dumps(tags, ensure_ascii=False)}"
        ]
        
        if cover_name:
            frontmatter_lines.append(f"image: \"{cover_name}\"")
        
        frontmatter_lines.append("---\n")
        frontmatter = "\n".join(frontmatter_lines)
        
        md_file = os.path.join(post_dir, "index.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)
        
        logger.info(f"成功转换 issue #{issue.number} 到 {md_file}")
        return True
    except Exception as e:
        logger.exception(f"转换 issue #{issue.number} 时发生严重错误")
        error_file = os.path.join(output_dir, f"ERROR_{issue.number}.tmp")
        with open(error_file, "w") as f:
            f.write(f"Conversion failed: {str(e)}")
        return False

def main():
    args = parse_arguments()
    logger = setup_logger(args.debug)
    
    token = args.token or os.getenv("GITHUB_TOKEN")
    if not token:
        logger.error("Missing GitHub token")
        return
    
    try:
        auth = Auth.Token(token)
        g = Github(auth=auth)
        repo = g.get_repo(args.repo)
        logger.info(f"已连接至 GitHub 仓库：{args.repo}")
    except Exception as e:
        logger.error(f"连接GitHub失败: {str(e)}")
        return
    
    os.makedirs(args.output, exist_ok=True)
    logger.info(f"输出目录: {os.path.abspath(args.output)}")
    
    processed_count = 0
    error_count = 0
    
    try:
        issues = repo.get_issues(state="open")
        total_issues = issues.totalCount
        logger.info(f"开始处理 {total_issues} 个打开状态的 issue")
        
        for issue in issues:
            if issue.pull_request:
                continue
            try:
                if convert_issue(issue, args.output, token, logger):
                    processed_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"处理 issue #{issue.number} 时出错: {str(e)}")
                try:
                    error_comment = f"⚠️ 转换为Hugo内容失败，请检查格式错误:\n\n```\n{str(e)}\n```"
                    if len(error_comment) > 65536:
                        error_comment = error_comment[:65000] + "\n```\n...(内容过长，部分已省略)"
                    
                    issue.create_comment(error_comment)
                    try:
                        error_label = repo.get_label("conversion-error")
                    except:
                        error_label = repo.create_label("conversion-error", "ff0000")
                    issue.add_to_labels(error_label)
                except Exception as inner_e:
                    logger.error(f"创建评论或添加标签时出错: {inner_e}")
    except Exception as e:
        logger.exception(f"获取issues时出错: {e}")
        
    summary = f"处理完成！成功转换 {processed_count} 个issues，{error_count} 个错误"
    if processed_count == 0:
        logger.info(summary + " - 没有需要处理的内容变更")
    else:
        logger.info(summary)
        
    if args.debug:
        logger.debug("内容目录状态:")
        logger.debug(os.listdir(args.output))

def parse_arguments():
    parser = argparse.ArgumentParser(description='Convert GitHub issues to Hugo content')
    parser.add_argument('--token', type=str, default=None, help='GitHub access token')
    parser.add_argument('--repo', type=str, required=True, help='GitHub repository in format owner/repo')
    parser.add_argument('--output', type=str, default='content/posts', help='Output directory')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    return parser.parse_args()

if __name__ == "__main__":
    main()