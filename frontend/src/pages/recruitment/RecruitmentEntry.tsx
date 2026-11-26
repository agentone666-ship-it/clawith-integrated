import { Link } from 'react-router-dom';

export function RecruitmentEntry() {
    return <div style={{ padding: '16px 32px 0', display: 'flex', justifyContent: 'flex-end' }}>
        <Link className="btn btn-primary" to="/recruitment">招聘数字员工</Link>
    </div>;
}
