output "runner_url" {
  value = "http://${aws_lb.this.dns_name}:8090"
}

output "asg_name" {
  value = aws_autoscaling_group.this.name
}

output "target_group_arn_suffix" {
  value = aws_lb_target_group.this.arn_suffix
}

output "nlb_arn_suffix" {
  value = aws_lb.this.arn_suffix
}
