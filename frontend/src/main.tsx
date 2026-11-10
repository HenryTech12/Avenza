import { render } from 'preact'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/themes.css'
import './styles/base.css'
import './styles/screens.css'
import { App } from './app/App'

render(<App />, document.getElementById('app')!)
