# Safe web import

Web import accepts only public HTTP and HTTPS pages. Validate every redirect, reject private addresses, and pin connections to validated IPs to prevent DNS rebinding. Agent tools must be allowlisted.

网页导入阻断私网与云元数据地址，逐次校验重定向并绑定已验证 IP。工具白名单不包含任意 Shell。