# 함께 배포하는 외부 프로그램

## rhwp

한글 없이 HWP/HWPX 문서를 쪽 이미지로 그리고 HWP를 HWPX로 바꾸는 데 씁니다.
한큐는 rhwp 실행 파일을 별도 프로그램으로 실행만 하며, 코드를 섞지 않습니다.

- 출처: https://github.com/edwardkim/rhwp
- 버전: `hanq/hwp/rhwp.py`의 `RHWP_VERSION` (빌드 때 `tools/fetch_rhwp.py`가 공식 릴리스를 받아 SHA256을 확인)
- 라이선스: MIT — 전문은 설치 폴더의 `tools/rhwp/LICENSE`

## 참고한 프로젝트 (코드는 가져오지 않음)

- hwpx_new (https://github.com/ZZombie04/hwpx_new, MIT): 서식을 '서식 종류'로 묶어 같은 서식의 새 문서를 만드는 방식
- kordoc (https://github.com/chrisryugj/kordoc, MIT), python-hwpx (https://github.com/airmang/python-hwpx, Apache-2.0):
  HWP/HWPX 처리 방식 조사
