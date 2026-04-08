크롤링 엔진: crawl4ai (AsyncWebCrawler, LLMContentFilter)
AI 모델: ollama
HTML 처리: BeautifulSoup
비동기 처리: asyncio

프로세스 1: 사이트 맵핑 (모든 유효 URL 수집)
가장 먼저, 우리가 처리해야 할 대상이 몇 개인지 알아야 합니다. crawl4ai의 딥크롤링 기술을 사용하여 사이트 전체를 스캔하여 방문 가능한 모든 페이지의 url를 수집했습니다. 

 

사용한 기술: crawl4ai의 BFSDeepCrawlStrategy (너비 우선 탐색)

체계적인 탐색 (BFS > DFS): 모든 링크를 빠짐없이 찾는 것이 목표일 때, BFS(너비 우선)는 가장 체계적이고 안정적인 방법입니다. 1단계 깊이의 모든 링크를 찾고, 그다음 2단계 깊이의 모든 링크를 찾는 방식이죠. 반면 DFS(깊이 우선)는 특정 경로에 너무 깊이 빠져(예: 무한 캘린더 페이지) 다른 중요한 섹션을 놓칠 위험이 있습니다.
명확한 경계 설정 (include_external=False): 저의 목표는 github.com 내부 콘텐츠입니다. include_external=False 옵션은 크롤러가 외부 SNS, 블로그, 광고 링크로 빠져나가 자원을 낭비하는 것을 막아줍니다.
작업의 분리 (Separation of Concerns): "URL 수집"과 "콘텐츠 처리"는 완전히 다른 작업입니다. 이 두 작업을 분리하면, URL 수집이 실패하더라도 이미 처리한 콘텐츠는 안전하며, 나중에 콘텐츠 처리만 재시도할 수 있어 매우 안정적이고 효율적인 파이프라인이 됩니다.

# 1단계: URL 수집 코드 예시
deep_crawl_config = BFSDeepCrawlStrategy(
    max_depth=5,          # 사이트 구조에 맞춰 적절한 깊이
    include_external=False, # 우리 도메인에만 집중
    max_pages=500         # 서버 부담을 줄이기 위한 안전장치
)

import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy

async def main():
    # 크롤링할 시작 URL
    start_url = " "
    
    # 딥크롤링 전략 설정
    deep_crawl_config = BFSDeepCrawlStrategy(
        max_depth=5,  
        # include_external=False: 해당 도메인 내의 링크만 수집
        include_external=False, 
        max_pages=500 
    )

    # 전체 크롤러 실행 설정
    config = CrawlerRunConfig(
        deep_crawl_strategy=deep_crawl_config,
        scraping_strategy=LXMLWebScrapingStrategy(),
        verbose=True  # 크롤링 진행 상황을 콘솔에 출력
    )
    
    # 수집된 고유 링크를 저장할 Set
    collected_links = set()

    print(f"크롤링을 시작합니다. 대상: {start_url}")

    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun(start_url, config=config)
        
        for result in results:
            if result.url:
                collected_links.add(result.url)

    print(f"\n--- 크롤링 완료 ---")
    print(f"총 {len(collected_links)}개의 고유한 링크를 수집했습니다.")
    
    # 수집된 링크 목록을 정렬하여 반환
    return sorted(list(collected_links))


# --- 메인 실행 부분 ---
if __name__ == "__main__":
    # main 함수를 실행하고 URL 리스트를 받음
    url_list = asyncio.run(main())
    
    # URL 리스트를 파일에 저장
    output_filename = "collected_urls_test.txt"
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            for url in url_list:
                f.write(url + "\n") # 각 URL을 새 줄에 저장
        
        print(f"'{output_filename}' 파일에 {len(url_list)}개의 URL을 성공적으로 저장했습니다.")
        
    except Exception as e:
        print(f"파일 저장 중 오류가 발생했습니다: {e}")

수집한 URL을 이제 하나씩 처리합니다. 하지만 직접 해보시면 웹사이트는 requests.get()만으로는 원하는 HTML 구조를 모두 가져올 수 없다는 것을 아실겁니다.

사용한 기술: crawl4ai의 AsyncWebCrawler + BrowserConfig
자바스크립트 렌더링 대응: 특정 사이트는 EgovPageLink.do?link=...와 같이 URL 파라미터를 기반으로 자바스크립트가 콘텐츠를 동적으로 생성합니다. requests나 httpx 같은 단순 라이브러리는 텅 빈 껍데기 HTML만 가져옵니다. BrowserConfig(headless=True)는 crawl4ai가 백그라운드에서 실제 브라우저(Playwright)를 실행하도록 지시합니다. 이 브라우저는 자바스크립트를 모두 실행하여 사용자가 보는 최종 렌더링 결과(HTML)를 우리에게 전달합니다.
추상화의 편리함: Selenium이나 Playwright를 직접 쓰면 코드가 매우 복잡해집니다. crawl4ai는 이 복잡한 브라우저 제어를 crawler.arun(url)이라는 단 하나의 명령어로 추상화해 줍니다.

        browser_config = BrowserConfig(headless=True, verbose=False) # 루프 중에는 False 권장
    crawl_config = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED,
        delay_before_return_html=2 # html이 모두 랜더링 될 때까지 지연시간 추가
    )
    
    final_result = { "url": url, "combined_markdown": None }

    try:
        print(f"  [시작] 크롤링 시작: {url}")
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url, config=crawl_config)