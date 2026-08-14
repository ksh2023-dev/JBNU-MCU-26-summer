/**
 * contactMail.js — '교수님께 컨택하기' 공용 로직
 *
 * 메일 초안(제목·본문)을 만들고, 기본 메일 앱을 여는 mailto 링크를 조립합니다.
 * 화면과 분리한 이유: 나중에 다른 페이지에서도 같은 초안을 쓰기 위해서입니다.
 *
 * 지어내지 않기 원칙: 실제로 가진 값(교수 이름·학과)만 쓰고,
 *   모르는 정보(학생 소개·용건 등)는 지어내지 않고 빈칸 자리표시자로 둡니다.
 */

/**
 * 컨택 메일의 제목·본문 초안을 만듭니다.
 * @param {{name?: string, department?: string}} professor
 * @returns {{subject: string, body: string}}
 */
export function buildContactDraft(professor) {
  const name = professor?.name ?? '교수'
  const department = professor?.department ?? ''

  const subject = `[면담 요청] ${name} 교수님께 문의드립니다`

  const interest = department
    ? `${department} 분야의 연구에 관심이 있어 연락드립니다.`
    : `교수님의 연구에 관심이 있어 연락드립니다.`

  // 각 줄을 배열로 두고 \n 으로 잇습니다. (mailto 로 인코딩되면 줄바꿈이 %0A 로 바뀝니다)
  const body = [
    `${name} 교수님께,`,
    ``,
    `안녕하세요, 교수님.`,
    `[여기에 본인 소개를 적어주세요 — 소속 / 학년 / 이름]`,
    ``,
    interest,
    `[여기에 문의하실 내용을 구체적으로 적어주세요.]`,
    ``,
    `바쁘신 중에 읽어주셔서 감사합니다. 답변 기다리겠습니다.`,
    ``,
    `[본인 이름 / 연락처]`,
  ].join('\n')

  return { subject, body }
}

/**
 * mailto 링크 문자열을 만듭니다. 제목·본문은 반드시 인코딩합니다.
 * @returns {string} 'mailto:...' 형태의 링크
 */
export function toMailtoHref(email, subject, body) {
  const query = `subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
  return `mailto:${email}?${query}`
}

/**
 * 기본 메일 앱을 엽니다.
 * SPA 화면 전환에 영향을 주지 않도록 임시 <a> 를 만들어 클릭시킵니다.
 * (mailto 는 사용자 PC의 '기본 메일 앱'을 엽니다. 설정돼 있지 않으면 안 열릴 수 있습니다.)
 */
export function openMailto(href) {
  const link = document.createElement('a')
  link.href = href
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
}
