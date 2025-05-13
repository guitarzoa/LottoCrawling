// page/fetch-last-game.js
const fs = require('fs');
const axios = require('axios');
const { JSDOM } = require('jsdom');

(async () => {
  try {
    const proxyUrl  = 'https://api.allorigins.win/raw?url=';
    const targetUrl = 'https://www.dhlottery.co.kr/gameResult.do?method=byWin';

    // HTML 가져오기
    const res = await axios.get(proxyUrl + encodeURIComponent(targetUrl));
    const dom = new JSDOM(res.data);

    // meta[name="description"]#desc 의 content 에서 마지막 회차 추출
    const meta = dom.window.document.querySelector('meta#desc[name="description"]');
    if (!meta) throw new Error('meta#desc[name="description"] 를 찾을 수 없습니다.');
    const content = meta.content;
    const s = content.indexOf(' ') + 1;
    const e = content.indexOf('회');
    const lastGame = content.substring(s, e);

    // JSON 파일로 저장
    const out = { lastGame };
    fs.writeFileSync('lastGame.json', JSON.stringify(out, null, 2), 'utf-8');
    console.log('✅ lastGame.json 생성됨:', out);
  } catch (err) {
    console.error('❌ 데이터 가져오기 실패:', err);
    process.exit(1);
  }
})();
