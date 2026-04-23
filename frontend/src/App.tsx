import { Link, Route, Routes } from "react-router-dom";
import { Library } from "./pages/Library";
import { DocumentView } from "./pages/DocumentView";

export default function App() {
  return (
    <div className="app">
      <div className="topbar">
        <h1>
          <Link to="/" style={{ color: "inherit" }}>Studious</Link>
        </h1>
        <span className="badge">Japanese study tool · MVP</span>
        <div className="spacer" />
      </div>
      <Routes>
        <Route path="/" element={<Library />} />
        <Route path="/doc/:id" element={<DocumentView />} />
      </Routes>
    </div>
  );
}
