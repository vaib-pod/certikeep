import { Link } from 'react-router-dom'
import WindowDots from '../components/WindowDots'

export default function Landing() {
  return (
    <div className="landing page-frame">
      <WindowDots />
      <div className="brand">CertiKeep<span className="spark">✦</span></div>
      <div className="landing-copy">
        <h1>Your personalized digital assistant to keep<br/>your documents handy</h1>
        <p>Store it once. Find it or ask about it whenever you need it.</p>
        <div className="landing-actions"><Link className="pixel-btn primary" to="/register">Create your vault →</Link><Link className="pixel-btn" to="/login">Log in</Link></div>
      </div>
      
      <div className="folder-row">
        <div className="folder yellow-folder"><span>▤</span><h2>Certificates</h2><p>Degrees, courses, achievements</p></div>
        <div className="folder cyan-folder"><span>▣</span><h2>IDs</h2><p>Aadhaar, PAN, passport and more</p></div>
        <div className="folder green-folder"><span>▤</span><h2>Other Docs</h2><p>Offer letters, records and more</p></div>
      </div>
    </div>
  )
}
