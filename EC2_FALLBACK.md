# Consensus EC2 fallback runbook

Use this only if the Tokyo App Runner pipeline has not recovered within 20 minutes.
Do not keep debugging App Runner in parallel.

## Fixed configuration

- Region: `ap-northeast-1`
- Instance: Amazon Linux 2023, `t3.small`
- Network: default VPC and a default public subnet
- Access: AWS Systems Manager Session Manager; no key pair and no inbound port 22
- Inbound traffic: TCP 80 only
- Container: the same immutable Git-SHA image already pushed to the `consensus` ECR repository
- Runtime: one container, `80:8080`, restart policy `unless-stopped`

## Preparation

1. Resolve the latest Amazon Linux 2023 x86_64 AMI from the public SSM parameter
   `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`.
2. Create `ConsensusEc2FallbackRole` trusted by `ec2.amazonaws.com` and attach:
   - `AmazonSSMManagedInstanceCore`
   - `AmazonEC2ContainerRegistryReadOnly`
3. Create an instance profile with that role.
4. Create security group `consensus-ec2-fallback` in the default VPC with inbound TCP 80
   from `0.0.0.0/0`; do not add an SSH rule.

## User data behavior

The launch user data must:

1. Install and start Docker.
2. Authenticate Docker to ECR in `ap-northeast-1` using the instance role.
3. Pull the already verified immutable image URI.
4. Start it as:

```bash
docker run -d \
  --name consensus \
  --restart unless-stopped \
  -p 80:8080 \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e OPENAI_MODEL=gpt-6-astra \
  -e OPENAI_TIMEOUT_SECONDS=60 \
  "$CONSENSUS_IMAGE_URI"
```

Pass the OpenAI key only through protected launch-time user data. Never commit it to this
repository or write it into the AMI. The statistical path remains functional if the key is
omitted.

## Acceptance and handoff

1. Wait until both EC2 status checks pass and the instance appears as an SSM managed node.
2. Verify `http://PUBLIC_IP/api/health` returns HTTP 200.
3. Run `scripts/load_demo.py --base-url http://PUBLIC_IP` and record the room code.
4. Verify the browser displays `LIVE API` and the result page matches the API JSON.
5. Share the HTTP URL only after these checks pass.

## Cleanup

At the same 24-hour cleanup point as the App Runner deployment, terminate the fallback instance
if it was created, then delete its security group, instance profile, and dedicated IAM role.
Do not delete the default VPC or public subnet.
