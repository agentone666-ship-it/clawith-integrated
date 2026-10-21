import { Link } from 'react-router-dom';

export function EmployeeStudioEntry() {
    return <div style={{ padding: '16px 32px 0', display: 'flex', justifyContent: 'flex-end' }}>
        <Link className="btn btn-primary" to="/employee-studio">数字员工开发工作台</Link>
    </div>;
}
