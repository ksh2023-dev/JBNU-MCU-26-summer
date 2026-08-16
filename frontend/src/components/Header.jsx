import { NavLink } from 'react-router-dom'

// 실제로 존재하는 페이지만 메뉴로 연결한다
const MENUS = [
  { to: '/', label: '교수 검색' },
  { to: '/favorites', label: '내 저장' },
]

function Header() {
  return (
    <header className="app-header">
      <div className="app-header__inner">
        {/* 로고를 누르면 메인으로 */}
        <NavLink to="/" className="app-header__logo">
          연구매칭
        </NavLink>

        <nav className="app-header__nav">
          {MENUS.map((menu) => (
            <NavLink
              key={menu.to}
              to={menu.to}
              // NavLink는 현재 주소와 일치하면 isActive를 true로 준다.
              // end: "/" 메뉴가 모든 주소에서 활성으로 보이는 것을 막아준다.
              end={menu.to === '/'}
              className={({ isActive }) =>
                isActive ? 'app-header__link is-active' : 'app-header__link'
              }
            >
              {menu.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  )
}

export default Header
